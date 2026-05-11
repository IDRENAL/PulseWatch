import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def hash_password(password: str) -> str:
    # Генерируем соль и хешируем
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Проверяем соответствие пароля хешу
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(subject: str | int, expires_delta: timedelta | None = None) -> str:
    if expires_delta is not None:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode = {"exp": expire, "sub": str(subject), "type": "access"}
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def create_refresh_token(subject: str | int) -> tuple[str, str]:
    """Создаёт refresh-токен и возвращает (jwt, jti).

    jti нужен для whitelist в Redis — позволяет отзывать конкретные сессии
    без инвалидации всех refresh-токенов юзера.
    """
    jti = secrets.token_urlsafe(16)
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh", "jti": jti}
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt, jti


def decode_refresh_token(token: str) -> tuple[int, str]:
    """Декодирует refresh-токен. Бросает JWTError при невалидности / неправильном типе.

    Returns (user_id, jti). Проверка наличия jti в Redis — отдельно, на вызывающей стороне.
    """
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    if payload.get("type") != "refresh":
        raise JWTError("not a refresh token")
    sub = payload.get("sub")
    jti = payload.get("jti")
    if sub is None or jti is None:
        raise JWTError("missing sub or jti")
    return int(sub), str(jti)
