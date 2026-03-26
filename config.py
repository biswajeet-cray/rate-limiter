from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API
    app_name: str = "Rate Limiter Service"
    debug: bool = False

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # Storage backend: "memory" or "redis"
    storage_backend: str = "memory"

    # Rate limiting defaults
    default_max_requests: int = 100
    default_window_seconds: int = 60

    model_config = {"env_prefix": "RATELIMITER_"}


settings = Settings()
