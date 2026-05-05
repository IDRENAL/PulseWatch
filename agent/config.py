from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    api_url: str = "http://127.0.0.1:8000"
    api_key: str
    send_interval_seconds: float = 10.0
    request_timeout_seconds: float = 5.0
    logs_enabled: bool = True
    logs_ws_path: str = "/ws/agent/logs"
    logs_reconnect_max_seconds: float = 30.0

    @property
    def ws_base_url(self) -> str:
        # http://… → ws://…, https://… → wss://…
        if self.api_url.startswith("https://"):
            return "wss://" + self.api_url[len("https://") :]
        if self.api_url.startswith("http://"):
            return "ws://" + self.api_url[len("http://") :]
        return self.api_url

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGENT_",
        extra="ignore",
    )


settings = AgentSettings()
