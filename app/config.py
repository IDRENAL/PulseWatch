from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    db_user: str
    db_password: str
    db_host: str = 'localhost'
    db_port: int = 5432
    db_name: str = 'pulsewatch'
    redis_host: str = 'localhost'
    redis_port: int = 6379
    secret_key: str
    algorithm: str = 'HS256'
    access_token_expire_minutes: int = 30


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}"



settings = Settings()


