from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # TOTP — pyotp хранит secret base32; в БД лежит «голым» (как у большинства реализаций).
    # Для прода хочется шифровать через KMS, но для учебного хватит.
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Тариф для лимитов на серверы/правила. Значения: free | pro | enterprise.
    # Хранится строкой, а не enum, чтобы добавлять новые планы без миграции.
    subscription_tier: Mapped[str] = mapped_column(
        String(32), nullable=False, default="free", server_default="free"
    )
