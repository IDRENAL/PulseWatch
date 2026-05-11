from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str  # обычно "bearer"


class TokenPayload(BaseModel):
    sub: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str
