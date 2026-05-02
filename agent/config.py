from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    api_url: str = "http://127.0.0.1:8000"
    api_key: str
    send_interval_seconds: float = 10.0
    request_timeout_seconds: float = 5.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGENT_",
        extra="ignore",
    )


settings = AgentSettings()
