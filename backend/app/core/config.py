"""Application settings, loaded from environment variables only.

No secret has a usable default: production refuses to start when a required
secret is missing or looks like a placeholder.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
EmailTransport = Literal["none", "console", "smtp", "ses"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None, extra="ignore", case_sensitive=False, populate_by_name=True
    )

    environment: Environment = "local"
    app_name: str = "STREAMCLIP"
    # Public origin of the web application (links in e-mails, Stripe return URLs).
    public_app_url: str = "http://localhost:3000"
    log_level: str = "INFO"
    release: str = Field(default="dev", validation_alias="VERCEL_GIT_COMMIT_SHA")

    # --- Database -----------------------------------------------------------
    database_url: SecretStr
    # Direct (non-pooled) endpoint used by migrations. Defaults to database_url.
    database_migration_url: SecretStr | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_statement_timeout_ms: int = 15_000

    # --- Authentication -----------------------------------------------------
    # "kid:secret[,kid:secret...]". The first key signs; every key verifies,
    # which allows rotation without logging users out.
    jwt_signing_keys: SecretStr
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 30
    session_max_age_days: int = 90
    refresh_reuse_grace_seconds: int = 20
    email_verification_ttl_hours: int = 48
    password_reset_ttl_minutes: int = 60
    # Minimum duration of the "forgot password" answer, so that its timing does
    # not reveal whether an address has an account.
    password_reset_response_floor_seconds: float = 1.0
    terms_version: str = "2026-11-16"
    registration_open: bool = True
    # Shared secret proving a request comes from our own web front-end (BFF),
    # which is then trusted to forward the end user's IP address.
    bff_shared_secret: SecretStr | None = None

    # --- E-mail -------------------------------------------------------------
    email_transport: EmailTransport = "none"
    email_from: str = "STREAMCLIP <no-reply@localhost>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    ses_region: str | None = None

    # --- Stripe -------------------------------------------------------------
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None

    # --- Object storage (S3) ------------------------------------------------
    # Custom names: Vercel reserves the AWS_* variables for its own runtime.
    s3_bucket: str | None = None
    s3_region: str | None = None
    # Bootstrap keys (iamuser2): used ONLY to call sts:AssumeRole.
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_endpoint_url: str | None = None
    data_export_ttl_days: int = 7

    # --- AWS AssumeRole (all service calls use the role, not the bootstrap key)
    aws_role_arn: str | None = None
    aws_role_session_name: str = "streamclip-api"
    aws_role_duration_seconds: int = 3600

    # --- Ingest (per-org MediaMTX t4g.small spot) ----------------------------
    # Users get PUBLIC_APP_URL/rtmp?key=… → quota check → start unique spot →
    # 302 rtmp://{instance-ip}:1935/live. No shared fallback host.
    ingest_hook_secret: SecretStr | None = None
    ingest_api_auth_url: str | None = None
    ingest_api_event_url: str | None = None
    # EC2 launch (required in staging/production for real spots).
    ingest_ec2_ami_id: str | None = None
    ingest_ec2_subnet_id: str | None = None
    ingest_ec2_security_group_id: str | None = None
    ingest_ec2_instance_profile: str | None = None
    ingest_ec2_instance_type: str = "t4g.small"
    ingest_ec2_region: str | None = None
    # Legacy optional SRT template (advanced).
    ingest_srt_url: str | None = None
    # Deprecated: ignored for resolve (no shared host). Kept for env compat.
    ingest_public_host: str | None = None
    ingest_rtmps_url: str | None = None

    # --- ASR / transcription ------------------------------------------------
    # none | console | openai_compatible (Groq/OpenAI-compatible HTTP).
    asr_provider: str = "none"
    asr_api_key: SecretStr | None = None
    asr_base_url: str = "https://api.groq.com/openai/v1"
    asr_model: str = "whisper-large-v3-turbo"

    # --- Bedrock multimodal (OpenAI GPT-6 Luna) -----------------------------
    # Luna is served via cross-Region inference on bedrock-runtime (US profile).
    bedrock_region: str | None = "us-east-1"
    bedrock_model: str = "us.openai.gpt-6-luna"
    # Length of each recorded HD segment on the ingest instance (seconds).
    segment_duration_sec: int = 300

    # --- Operations ---------------------------------------------------------
    cron_secret: SecretStr | None = None
    max_request_body_bytes: int = 1_048_576
    vat_rate_percent: float = 20.0

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def email_enabled(self) -> bool:
        return self.email_transport != "none"

    @property
    def billing_enabled(self) -> bool:
        return self.stripe_secret_key is not None

    @property
    def stripe_livemode(self) -> bool | None:
        if self.stripe_secret_key is None:
            return None
        key = self.stripe_secret_key.get_secret_value()
        return key.startswith(("sk_live_", "rk_live_"))

    @property
    def storage_enabled(self) -> bool:
        has_bootstrap = (
            self.s3_access_key_id is not None and self.s3_secret_access_key is not None
        )
        return bool(self.s3_bucket and self.s3_region and has_bootstrap)

    @property
    def ingest_launcher_configured(self) -> bool:
        return bool(
            self.ingest_ec2_ami_id
            and self.ingest_ec2_subnet_id
            and self.ingest_ec2_security_group_id
        )

    @property
    def ingest_online(self) -> bool:
        # Ready to start per-org spots (AWS configured, or local/test fake launcher).
        return self.ingest_launcher_configured or self.environment in ("local", "test")

    def jwt_keyring(self) -> dict[str, str]:
        keyring: dict[str, str] = {}
        for item in self.jwt_signing_keys.get_secret_value().split(","):
            kid, sep, secret = item.strip().partition(":")
            if not sep or not kid or not secret:
                raise ValueError("JWT_SIGNING_KEYS must look like 'kid:secret[,kid:secret]'")
            keyring[kid] = secret
        return keyring

    @model_validator(mode="after")
    def _validate(self) -> Self:
        keyring = self.jwt_keyring()
        if self.environment in ("staging", "production"):
            problems = []
            if any(len(secret) < 43 for secret in keyring.values()):
                problems.append("JWT_SIGNING_KEYS secrets must be at least 32 random bytes")
            if not self.public_app_url.startswith("https://"):
                problems.append("PUBLIC_APP_URL must use https")
            if self.email_transport == "console":
                problems.append("EMAIL_TRANSPORT=console would write secrets to logs")
            if self.bff_shared_secret is None:
                problems.append("BFF_SHARED_SECRET is required")
            if self.cron_secret is None:
                problems.append("CRON_SECRET is required")
            if self.stripe_secret_key is not None and self.stripe_webhook_secret is None:
                problems.append("STRIPE_WEBHOOK_SECRET is required when Stripe is enabled")
            if problems:
                raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
