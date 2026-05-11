import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
    is_refresh_jti_used,
    revoke_all_refresh_for_user,
    revoke_refresh_jti,
    rotate_refresh_jti,
    store_refresh_jti,
    store_tg_link_code,
)
from app.schemas.token import RefreshRequest, Token
from app.schemas.user import (
    EmailAlertsToggle,
    TelegramLink,
    TelegramLinkCode,
    UserCreate,
    UserRead,
)

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

    # 4. Возвращаем созданного юзера
    return new_user


@router.post("/login", response_model=Token, status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    # ШАГ 1: достать юзера
    query = select(User).where(User.email == form_data.username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    # ШАГ 2: проверить пароль и наличие юзера
    if user is None or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # ШАГ 3: создать пару (access + refresh), refresh — в whitelist Redis
    access = create_access_token(subject=user.id)
    refresh, jti = create_refresh_token(subject=user.id)
    await store_refresh_jti(user.id, jti, _REFRESH_TTL_SECONDS)

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
