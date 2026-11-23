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
    public_rate_limit_per_minute: int = 300  # per address, anonymous readers (0 turns it off)
    public_cache_enabled: bool = True  # shared short-lived cache for public reads (tests turn it off)
    public_ws_per_ip: int = 5  # simultaneous anonymous live sockets per address
    public_ws_total: int = 3000  # and across the whole server
    push_enabled: bool = False  # browser push needs VAPID keys (python -m app.make_vapid)
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@ffcl.example"  # who a push service can contact about this server
    push_dry_run: bool = False  # log pushes instead of sending them (staging, browser tests)
    push_max_devices_per_user: int = 10
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
    if s.push_enabled and not (s.vapid_public_key and s.vapid_private_key):
        raise RuntimeError("PUSH_ENABLED needs VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY (generate with python -m app.make_vapid)")
