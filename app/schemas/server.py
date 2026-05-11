from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ServerCreate(BaseModel):
    name: str


class ServerRead(BaseModel):
    id: int
    name: str
    is_active: bool
    paused: bool = False
    created_at: datetime
    last_seen_at: datetime | None
    agent_version: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ServerWithKey(ServerRead):
    api_key: str
