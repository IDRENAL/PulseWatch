from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    id: int
    email: EmailStr
    is_active: bool
    created_at: datetime
    telegram_chat_id: str | None = None
    email_alerts_enabled: bool = True
    totp_enabled: bool = False
    subscription_tier: str = "free"

    model_config = ConfigDict(from_attributes=True)


class QuotaUsage(BaseModel):
    """Текущее использование и лимиты тарифа. -1 в *_max = безлимит."""

    tier: str
    servers_used: int
    servers_max: int
    rules_used: int
    rules_max: int


class EmailAlertsToggle(BaseModel):
    """Переключатель email-уведомлений для текущего юзера."""

    enabled: bool


class TotpSetupResponse(BaseModel):
    """Ответ /auth/me/totp/setup: secret и otpauth-URL для QR."""

    secret: str
    otpauth_url: str


class TotpVerifyRequest(BaseModel):
    code: str


class TotpDisableRequest(BaseModel):
    password: str


class TelegramLink(BaseModel):
    chat_id: str | None

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("chat_id не может быть пустой строкой")

        # Telegram chat_id — целое число (для групп — отрицательное)
        if not (v.lstrip("-").isdigit() and v != "-"):
            raise ValueError("chat_id должен быть целым числом")
        return v


class TelegramLinkCode(BaseModel):
    """Ответ на POST /auth/me/telegram/code: одноразовый код привязки + deep-link."""

    code: str
    deep_link: str | None = (
        None  # https://t.me/<bot>?start=<code>, если bot_username сконфигурирован
    )
    expires_in_seconds: int
