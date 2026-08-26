from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost/tradedash"
    UPSTASH_REDIS_URL: str = ""
    UPSTASH_REDIS_TOKEN: str = ""
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440
    BOT_TOKEN: str = ""
    CHAT_ID: str = ""
    BOT2_TOKEN: str = ""
    BOT2_CHAT_ID: str = ""
    PAPER_TRADING: bool = True
    CAPITAL_PER_TRADE: float = 10000.0
    FORCE_EXIT_TIME: str = "15:12"
    # Store as comma-separated string — avoids pydantic-settings JSON parsing issues
    CORS_ORIGINS_STR: str = "http://localhost:3000"

    @property
    def CORS_ORIGINS(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS_STR.split(",") if o.strip()]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
