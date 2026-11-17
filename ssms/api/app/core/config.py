"""Settings from environment variables (prefix SSMS_). Secrets never have usable defaults in production."""

import base64
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-jwt-secret-do-not-use-in-production-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SSMS_", extra="ignore")

    environment: str = "development"  # development | test | production

    # Runtime database: login role ssms_app (NOBYPASSRLS). database_set_role is only for local setups
    # that connect as another login and must switch to ssms_app.
    database_url: str = "postgresql+psycopg://ssms_app@localhost:5432/ssms"
    database_set_role: str | None = None
    db_pool_size: int = 10
    # Super-admin console: ssms_platform is NOLOGIN, so a separate login that is a member of it connects
    # and switches with SET ROLE.
    platform_database_url: str = "postgresql+psycopg://ssms_console@localhost:5432/ssms"
    platform_database_set_role: str | None = "ssms_platform"
    # Migrations only (alembic): a role that may create roles and the btree_gist extension. Never used at runtime.
    migration_database_url: str = "postgresql+psycopg://postgres@localhost:5432/ssms"

    redis_url: str | None = None  # None = in-memory rate limits (dev/test only)
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_eager: bool = False
    tasks_inline: bool = False  # dev/E2E without Redis: run tasks in the API process

    jwt_secret: str = DEV_JWT_SECRET
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    parent_refresh_token_days: int = 30
    selection_token_minutes: int = 5
    cookie_secure: bool = True
    refresh_cookie_name: str = "ssms_rt"

    # Field encryption: "1:<base64 32 bytes>,2:<base64 32 bytes>"; active id encrypts, all ids decrypt.
    enc_keys: str = ""
    enc_active_key_id: int = 1
    blind_index_key: str = ""  # base64, 32+ bytes

    max_failed_logins: int = 5
    lockout_minutes: int = 15
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_requests_per_window: int = 3
    otp_window_seconds: int = 900
    login_attempts_per_minute: int = 10
    log_format: str | None = None  # text | json (default: json in production)
    sentry_dsn: str = ""  # error reporting, off when empty
    sentry_traces_sample_rate: float = 0.0
    metrics_token: str = ""  # when set, /metrics needs Authorization: Bearer <token>
    webhook_requests_per_minute: int = 6000  # per source IP: GePG and aggregators send bursts from few IPs

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    storage_dir: str = "./storage"
    # Files: a local folder (one server) or S3-compatible object storage (several API hosts, off-host copies).
    storage_backend: str = "local"  # local | s3
    s3_endpoint_url: str = ""  # empty = AWS; e.g. http://minio:9000
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    # Virus scanning of uploads with ClamAV (clamd over TCP). Production needs it unless explicitly turned off.
    clamav_address: str = ""  # host:port, e.g. clamav:3310
    allow_unscanned_uploads: bool = False
    max_import_bytes: int = 10 * 1024 * 1024

    sms_provider: str = "console"  # console | beem | nextsms
    beem_api_key: str = ""
    beem_secret_key: str = ""
    nextsms_username: str = ""
    nextsms_password: str = ""
    sms_default_sender: str = "SSMS"
    sms_webhook_secret: str = ""  # token in the delivery-report URL given to the SMS provider

    # Email (FR-98): console in development; smtp needs the server below.
    email_provider: str = "console"  # console | smtp
    email_from: str = "no-reply@ssms.local"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True  # STARTTLS on a plain connection (port 587)
    smtp_implicit_tls: bool = False  # TLS from the first byte (always on for port 465)
    smtp_ca_file: str = ""  # PEM bundle, only for a mail server whose certificate comes from a private CA

    # Payments. GePG and aggregator message formats are VERIFY items (design/01-introduction V4, V6).
    gepg_mode: str = "simulator"  # simulator (development) | live
    gepg_url: str = ""  # GePG bill submission endpoint
    gepg_private_key: str = ""  # our service-provider RSA key (PEM), signs requests/ACKs
    gepg_public_key: str = ""  # GePG RSA public key (PEM), verifies callbacks
    gepg_bill_days: int = 30  # control-number validity
    mobile_webhook_secret: str = ""  # HMAC-SHA256 key shared with the mobile-money aggregator
    push_provider: str = "console"  # console (development) | aggregator

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def email_enabled(self) -> bool:
        """In production the console provider would only log: email is then off rather than falsely 'sent'."""
        return self.email_provider == "smtp" or not self.is_production

    def encryption_keys(self) -> dict[int, bytes]:
        keys: dict[int, bytes] = {}
        for item in filter(None, (p.strip() for p in self.enc_keys.split(","))):
            kid, b64 = item.split(":", 1)
            key = base64.b64decode(b64)
            if len(key) != 32:
                raise ValueError(f"encryption key {kid} must be 32 bytes")
            keys[int(kid)] = key
        return keys

    def blind_key(self) -> bytes:
        return base64.b64decode(self.blind_index_key) if self.blind_index_key else b""


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production:
        problems = []
        if s.jwt_secret == DEV_JWT_SECRET or len(s.jwt_secret) < 32:
            problems.append("SSMS_JWT_SECRET (>= 32 chars)")
        if s.enc_active_key_id not in s.encryption_keys():
            problems.append("SSMS_ENC_KEYS with the active key")
        if len(s.blind_key()) < 32:
            problems.append("SSMS_BLIND_INDEX_KEY (>= 32 bytes)")
        if s.redis_url is None:
            problems.append("SSMS_REDIS_URL")
        if s.tasks_inline:
            problems.append("SSMS_TASKS_INLINE must be false (use Celery workers)")
        if s.gepg_mode != "live" or not (s.gepg_private_key and s.gepg_public_key and s.gepg_url):
            problems.append("SSMS_GEPG_MODE=live with SSMS_GEPG_URL, SSMS_GEPG_PRIVATE_KEY, SSMS_GEPG_PUBLIC_KEY")
        if len(s.mobile_webhook_secret) < 32:
            problems.append("SSMS_MOBILE_WEBHOOK_SECRET (>= 32 chars)")
        if len(s.sms_webhook_secret) < 32:
            problems.append("SSMS_SMS_WEBHOOK_SECRET (>= 32 chars)")
        if s.sms_provider == "console":
            problems.append("SSMS_SMS_PROVIDER (beem or nextsms)")
        if s.email_provider == "smtp" and not s.smtp_host:
            problems.append("SSMS_SMTP_HOST (SSMS_EMAIL_PROVIDER=smtp)")
        if s.email_provider == "smtp" and not (s.smtp_starttls or s.smtp_implicit_tls or s.smtp_port == 465):
            problems.append("SSMS_SMTP_STARTTLS=true or SSMS_SMTP_IMPLICIT_TLS=true (mail must be encrypted)")
        if s.storage_backend == "s3" and not (s.s3_bucket and s.s3_access_key and s.s3_secret_key):
            problems.append("SSMS_S3_BUCKET, SSMS_S3_ACCESS_KEY, SSMS_S3_SECRET_KEY (SSMS_STORAGE_BACKEND=s3)")
        if not s.clamav_address and not s.allow_unscanned_uploads:
            problems.append("SSMS_CLAMAV_ADDRESS (or SSMS_ALLOW_UNSCANNED_UPLOADS=true to accept unscanned files)")
        if problems:
            raise RuntimeError("Missing production settings: " + ", ".join(problems))
    return s
