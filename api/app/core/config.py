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
    environment: str = "development"  # set to "production" on a real server
    auth_rate_limits_enabled: bool = True  # login / register / OTP request throttling
    trust_proxy: bool = False  # honour X-Forwarded-For (only behind a proxy you control)


settings = Settings()


def assert_production_safe(s: Settings) -> None:
    """Refuse to start a production server with development defaults."""
    if s.environment != "production":
        return
    if s.jwt_secret.startswith("change-me") or len(s.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET must be set to a strong random value (32+ characters) in production")
    if not s.auth_rate_limits_enabled:
        raise RuntimeError("Auth rate limits must stay enabled in production")
