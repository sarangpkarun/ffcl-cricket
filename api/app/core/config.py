from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://ffcl:ffcl@localhost:5432/ffcl"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-dev-secret-at-least-32-bytes-long"
    cors_origins: str = "http://localhost:3100,http://localhost:3000"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    otp_ttl_minutes: int = 5
    otp_max_attempts: int = 5
    otp_provider: str = "console"


settings = Settings()
