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

    model_config = ConfigDict(from_attributes=True)


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
