import secrets

import pyotp
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models.user import User
from app.redis_client import (
    consume_password_reset_token,
    is_refresh_jti_used,
    revoke_all_refresh_for_user,
    revoke_refresh_jti,
    rotate_refresh_jti,
    store_password_reset_token,
    store_refresh_jti,
    store_tg_link_code,
)
from app.schemas.token import ForgotPasswordRequest, RefreshRequest, ResetPasswordRequest, Token
from app.schemas.user import (
    EmailAlertsToggle,
    QuotaUsage,
    TelegramLink,
    TelegramLinkCode,
    TotpDisableRequest,
    TotpSetupResponse,
    TotpVerifyRequest,
    UserCreate,
    UserRead,
)
from app.services.audit import record_audit

_REFRESH_TTL_SECONDS = settings.refresh_token_expire_days * 24 * 60 * 60

router = APIRouter()


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register_user(request: Request, data: UserCreate, db: AsyncSession = Depends(get_db)):
    # 1. Проверяем, существует ли пользователь
    query = select(User).where(User.email == data.email)
    result = await db.execute(query)
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким email уже существует",
        )

    new_user = User(
        email=data.email,
        password_hash=hash_password(data.password),
    )

    # 3. Сохраняем в БД (повторная проверка на гонке двух параллельных регистраций)
    db.add(new_user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким email уже существует",
        ) from None
    await db.refresh(new_user)

    await record_audit(db, action="register", user_id=new_user.id, request=request)

    # 4. Возвращаем созданного юзера
    return new_user


@router.post("/login", response_model=Token, status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    totp_code: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    # ШАГ 1: достать юзера
    query = select(User).where(User.email == form_data.username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    # ШАГ 2: проверить пароль и наличие юзера
    if user is None or not verify_password(form_data.password, user.password_hash):
        await record_audit(
            db,
            action="login_failed",
            user_id=user.id if user else None,
            request=request,
            meta={"email": form_data.username},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # ШАГ 2.5: если у юзера включен TOTP — требуем второй фактор
    if user.totp_enabled and user.totp_secret:
        if not totp_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="TOTP_REQUIRED",
            )
        if not pyotp.TOTP(user.totp_secret).verify(totp_code, valid_window=1):
            await record_audit(
                db,
                action="login_failed",
                user_id=user.id,
                request=request,
                meta={"reason": "invalid_totp"},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid TOTP code",
            )

    # ШАГ 3: создать пару (access + refresh), refresh — в whitelist Redis
    access = create_access_token(subject=user.id)
    refresh, jti = create_refresh_token(subject=user.id)
    await store_refresh_jti(user.id, jti, _REFRESH_TTL_SECONDS)
    await record_audit(db, action="login", user_id=user.id, request=request)

    return Token(access_token=access, refresh_token=refresh, token_type="bearer")


@router.post("/refresh", response_model=Token)
@limiter.limit("5/minute")
async def refresh_tokens(request: Request, data: RefreshRequest):
    """Обменивает refresh-токен на новую пару (access + refresh). Старый refresh
    инвалидируется (rotation). Если jti уже отозван — 401.
    """
    creds_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )

    try:
        user_id, old_jti = decode_refresh_token(data.refresh_token)
    except JWTError:
        raise creds_exc from None

    # Reuse-detection: если jti уже был потрачен на ротацию, кто-то предъявляет
    # «украденный» (или просто старый) токен. Не знаем кто легитим — отзываем
    # все сессии юзера, пусть логинится заново на всех устройствах.
    if await is_refresh_jti_used(user_id, old_jti):
        await revoke_all_refresh_for_user(user_id)
        from loguru import logger

        logger.warning(
            "refresh reuse detected for user_id={}, jti={} — all sessions revoked",
            user_id,
            old_jti,
        )

        # Best-effort уведомление юзеру в Telegram (если привязан)
        try:
            from sqlalchemy import select

            from app.database import async_session_factory
            from app.models.user import User
            from app.services.telegram import (
                TelegramNotConfiguredError,
                TelegramSendError,
                send_message,
            )

            async with async_session_factory() as db:
                target_user = (
                    await db.execute(select(User).where(User.id == user_id))
                ).scalar_one_or_none()
            if target_user and target_user.telegram_chat_id:
                await send_message(
                    target_user.telegram_chat_id,
                    "⚠️ <b>Подозрительная активность</b>\n"
                    "Кто-то попытался использовать твой уже отозванный refresh-токен. "
                    "На всякий случай мы закрыли все твои сессии — пожалуйста, "
                    "залогинься заново и поменяй пароль, если не узнаёшь эту активность.",
                )
        except (TelegramNotConfiguredError, TelegramSendError, Exception) as exc:
            logger.info("reuse-detection tg notify skipped: {}", exc)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected. All sessions revoked, please log in again.",
        )

    new_access = create_access_token(subject=user_id)
    new_refresh, new_jti = create_refresh_token(subject=user_id)

    rotated = await rotate_refresh_jti(user_id, old_jti, new_jti, _REFRESH_TTL_SECONDS)
    if not rotated:
        # old_jti не было в whitelist — токен либо никогда не существовал, либо
        # истёк, либо его отозвали через logout. Просто 401, без панического сброса.
        # Свежий new_jti мы уже поставили в pipeline — откатываем, чтобы не висел.
        await revoke_refresh_jti(user_id, new_jti)
        raise creds_exc

    return Token(access_token=new_access, refresh_token=new_refresh, token_type="bearer")


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Принимает email, всегда возвращает 200 (не раскрываем какие email существуют).

    Если юзер найден — генерит одноразовый токен, кладёт в Redis с TTL, отправляет
    email со ссылкой `<FRONTEND_BASE_URL>/reset-password?token=<token>`.
    """
    user = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()
    if user is not None:
        token = secrets.token_urlsafe(32)
        await store_password_reset_token(token, user.id, settings.password_reset_token_ttl_seconds)
        # Best-effort отправка письма. Если SMTP не настроен — лог + всё равно 200.
        from app.services.email_alert import EmailNotConfiguredError, EmailSendError, send_email

        link = f"{settings.frontend_base_url}/reset-password?token={token}"
        try:
            await send_email(
                user.email,
                "[PulseWatch] Сброс пароля",
                (
                    "<p>Ты запросил сброс пароля для PulseWatch.</p>"
                    f'<p><a href="{link}">Открой эту ссылку</a> чтобы установить новый пароль. '
                    "Ссылка действительна 1 час.</p>"
                    "<p>Если ты не запрашивал сброс — просто игнорируй это письмо.</p>"
                ),
                f"Сброс пароля: {link} (1 час)",
            )
        except (EmailNotConfiguredError, EmailSendError) as exc:
            from loguru import logger

            logger.warning("forgot-password email send skipped: {}", exc)
    return {"status": "ok"}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Обменивает токен на новый пароль. Заодно отзывает все refresh-сессии юзера —
    если токен скомпрометирован, не оставляем атакующему путь через старые refresh.
    """
    if len(data.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Пароль должен быть не короче 6 символов",
        )

    user_id = await consume_password_reset_token(data.token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Токен сброса невалиден или истёк",
        )

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        # Юзер удалён между генерацией токена и сбросом — на всякий случай 400
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Юзер не найден")

    user.password_hash = hash_password(data.new_password)
    await db.commit()

    # Отзываем все refresh-токены — пользователь должен заново залогиниться везде
    await revoke_all_refresh_for_user(user_id)
    await record_audit(db, action="password_reset", user_id=user_id, request=request)
    return {"status": "ok"}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshRequest):
    """Отзывает refresh-токен. Идемпотентно: повторный logout с тем же токеном
    или с уже истёкшим — тоже 204.
    """
    try:
        user_id, jti = decode_refresh_token(data.refresh_token)
    except JWTError:
        return  # 204 — невалидный токен тоже считаем «и так уже отозванным»
    await revoke_refresh_jti(user_id, jti)


@router.get("/me", response_model=UserRead)
async def read_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/me/quota", response_model=QuotaUsage)
async def read_quota(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Текущее потребление и лимит тарифа — для UI «осталось X из Y серверов»."""
    from sqlalchemy import func

    from app.core.quotas import get_limits
    from app.models.alert_rule import AlertRule
    from app.models.server import Server

    limits = get_limits(current_user.subscription_tier)
    servers_used = await db.scalar(
        select(func.count()).select_from(Server).where(Server.owner_id == current_user.id)
    )
    rules_used = await db.scalar(
        select(func.count())
        .select_from(AlertRule)
        .join(Server, AlertRule.server_id == Server.id)
        .where(Server.owner_id == current_user.id)
    )
    return QuotaUsage(
        tier=current_user.subscription_tier,
        servers_used=servers_used or 0,
        servers_max=limits.max_servers,
        rules_used=rules_used or 0,
        rules_max=limits.max_rules,
    )


@router.patch("/me/telegram", response_model=UserRead)
async def link_telegram(
    data: TelegramLink,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    current_user.telegram_chat_id = data.chat_id
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.patch("/me/email-alerts", response_model=UserRead)
async def toggle_email_alerts(
    data: EmailAlertsToggle,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Включает/выключает email-уведомления об алертах для текущего юзера."""
    current_user.email_alerts_enabled = data.enabled
    await db.commit()
    await db.refresh(current_user)
    return current_user


# ─── TOTP setup / enable / disable ──────────────────────────────────────────


@router.post("/me/totp/setup", response_model=TotpSetupResponse)
async def setup_totp(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Генерирует новый TOTP secret и сохраняет его (но totp_enabled остаётся False
    пока юзер не подтвердит код через /me/totp/enable). Можно вызывать повторно —
    каждый раз новый secret, старый теряется.
    """
    secret = pyotp.random_base32()
    current_user.totp_secret = secret
    current_user.totp_enabled = False
    await db.commit()
    otpauth_url = pyotp.TOTP(secret).provisioning_uri(
        name=current_user.email,
        issuer_name="PulseWatch",
    )
    return TotpSetupResponse(secret=secret, otpauth_url=otpauth_url)


@router.post("/me/totp/enable", response_model=UserRead)
async def enable_totp(
    data: TotpVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Подтверждает TOTP-код против secret, выставляет totp_enabled=True."""
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="TOTP не инициализирован, начни с /setup")
    if not pyotp.TOTP(current_user.totp_secret).verify(data.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Неверный TOTP-код")
    current_user.totp_enabled = True
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/me/totp/disable", response_model=UserRead)
async def disable_totp(
    data: TotpDisableRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отключает TOTP. Требует подтверждение паролем — чтобы украденный access-токен
    нельзя было использовать для отключения 2FA.
    """
    if not verify_password(data.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный пароль")
    current_user.totp_secret = None
    current_user.totp_enabled = False
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/me/telegram/code", response_model=TelegramLinkCode)
async def create_telegram_link_code(
    current_user: User = Depends(get_current_user),
):
    """Генерирует одноразовый код для привязки Telegram через бота.

    Юзер отправляет боту `/start <code>`, бот ставит `chat_id` в users.
    Код действителен 10 минут, одноразовый.
    """
    code = secrets.token_hex(4)  # 8 hex-символов, ~4*10^9 вариантов
    await store_tg_link_code(code, current_user.id)

    deep_link = None
    if settings.telegram_bot_username:
        deep_link = f"https://t.me/{settings.telegram_bot_username}?start={code}"

    return TelegramLinkCode(code=code, deep_link=deep_link, expires_in_seconds=600)
