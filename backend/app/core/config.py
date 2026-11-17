from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "dev-only-insecure-secret-change-me-before-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SMS_", extra="ignore")

    environment: str = "development"
    school_name: str = "Shule ya Sekondari Mfano"
    database_url: str = "postgresql+psycopg://sms_app:change-me@localhost:5432/sms"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = INSECURE_DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    cors_origins: list[str] = ["http://localhost:5173"]
    storage_dir: str = "./storage"
    max_upload_bytes: int = 5 * 1024 * 1024
    period_minutes: int = 40

    sms_provider: str = "console"          # console | http
    sms_api_url: str = ""
    sms_api_key: str = ""
    sms_sender_id: str = "MFANO-SS"

    gepg_enabled: bool = False
    gepg_url: str = ""
    gepg_sp_code: str = ""
    gepg_public_cert_path: str = ""


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment == "production" and settings.jwt_secret == INSECURE_DEFAULT_SECRET:
        raise RuntimeError("SMS_JWT_SECRET must be set in production")
    return settings
