from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.server import Server
from app.core.security import verify_password


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    creds_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # 1. Декодируем токен
        payload = jwt.decode(
            token, 
            settings.secret_key,
            algorithms=[settings.algorithm]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise creds_exc
    except JWTError:
        raise creds_exc

    # 2. Ищем пользователя в базе
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    # 3. Проверка на наличие
    if user is None:
        raise creds_exc

    # 4. Возвращаем объект пользователя
    return user


async def verify_api_key(
    api_key: str | None = Depends(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> Server:
    invalid_key_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
    )

    if not api_key:
        raise invalid_key_exc

    # Формат ключа: "<server_id>.<secret>"
    try:
        server_id_str, secret = api_key.split(".", 1)
        server_id = int(server_id_str)
    except (ValueError, AttributeError):
        raise invalid_key_exc

    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()

    if server is None or not server.is_active:
        raise invalid_key_exc

    if not verify_password(secret, server.api_key_hash):
        raise invalid_key_exc

    return server


async def authenticate_ws_user(token: str | None, db: AsyncSession) -> User | None:
    """JWT-аутентификация для WS. Возвращает None при любой ошибке (без HTTPException)."""
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        user_id = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None

    result = await db.execute(select(User).where(User.id == int(user_id)))
    return result.scalar_one_or_none()


async def authenticate_ws_agent(
    api_key: str | None, db: AsyncSession
) -> Server | None:
    """API-key аутентификация для WS. Возвращает None при любой ошибке."""
    if not api_key:
        return None
    try:
        server_id_str, secret = api_key.split(".", 1)
        server_id = int(server_id_str)
    except (ValueError, AttributeError):
        return None

    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if server is None or not server.is_active:
        return None
    if not verify_password(secret, server.api_key_hash):
        return None
    return server