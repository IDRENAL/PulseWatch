from pydantic import BaseModel

class Token(BaseModel):
    access_token: str
    token_type: str  # обычно "bearer"


class TokenPayload(BaseModel):
    sub: str | None = None
