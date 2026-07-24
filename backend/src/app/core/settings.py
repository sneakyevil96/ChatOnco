import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_project_config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "projects"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    application_secret_file: Path | None = None
    database_url: str = (
        "postgresql+psycopg://screening_local:local-development-only@localhost:5432/"
        "screening_platform"
    )
    project_config_dir: Path = default_project_config_dir()
    whatsapp_provider: Literal["mock", "meta"] = "mock"
    whatsapp_secret_file: Path | None = None
    meta_graph_api_version: str | None = None
    meta_graph_api_base_url: str = "https://graph.facebook.com"
    meta_request_timeout_seconds: float = 15.0
    whatsapp_webhook_max_bytes: int = 1_000_000
    csrf_signing_key: str = "local-csrf-signing-key-change-before-deployment"
    security_hash_key: str = "local-security-hash-key-change-before-deployment"
    allowed_browser_origins: str = "http://localhost:8080,http://localhost:5173"
    session_cookie_name: str = "screening_session"
    csrf_cookie_name: str = "screening_csrf"
    cookie_samesite: Literal["lax", "strict"] = "lax"
    session_idle_minutes: int = 30
    session_absolute_hours: int = 8
    csrf_token_minutes: int = 60
    password_reset_minutes: int = 30
    failed_logins_before_lockout: int = 5
    initial_lockout_minutes: int = 15
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_minutes: int = 15
    outbox_poll_seconds: float = 2.0
    outbox_claim_seconds: int = 60
    outbox_max_attempts: int = 5
    retention_batch_size: int = Field(default=1000, ge=1, le=10_000)
    security_state_cleanup_days: int = Field(default=30, ge=1)
    operations_stale_outbox_minutes: int = Field(default=5, ge=1)
    structured_logging: bool = True
    api_docs_enabled: bool = True
    operator_panel_access_mode: Literal[
        "public",
        "vpn",
        "ip_allowlist",
        "identity_aware_proxy",
        "reverse_proxy_auth",
    ] = "public"
    restricted_panel_mfa_risk_accepted: bool = False
    https_termination_confirmed: bool = False
    storage_encryption_confirmed: bool = False
    backup_encryption_confirmed: bool = False
    backup_destination_separate_confirmed: bool = False
    backup_restore_test_confirmed: bool = False

    @model_validator(mode="before")
    @classmethod
    def load_application_secrets(cls, raw_values: Any) -> Any:
        if not isinstance(raw_values, dict):
            return raw_values
        values = dict(raw_values)
        secret_file = values.get("application_secret_file")
        if not secret_file:
            return values
        try:
            payload = json.loads(Path(secret_file).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("Application secret file is unavailable or invalid") from exc
        allowed = {"database_url", "csrf_signing_key", "security_hash_key"}
        if not isinstance(payload, dict) or set(payload) != allowed:
            raise ValueError(
                "Application secret file must contain exactly the required secret bindings"
            )
        if any(not isinstance(payload[key], str) or not payload[key] for key in allowed):
            raise ValueError("Application secret file contains an invalid secret binding")
        values.update(payload)
        return values

    @property
    def cookie_secure(self) -> bool:
        return self.app_env in {"staging", "production"}

    @property
    def browser_origins(self) -> set[str]:
        return {
            origin.strip().rstrip("/")
            for origin in self.allowed_browser_origins.split(",")
            if origin.strip()
        }

    @model_validator(mode="after")
    def reject_local_security_keys_in_deployed_environments(self) -> "Settings":
        if self.app_env in {"staging", "production"}:
            if self.csrf_signing_key.startswith("local-"):
                raise ValueError("A deployment-specific CSRF signing key is required")
            if self.security_hash_key.startswith("local-"):
                raise ValueError("A deployment-specific security hash key is required")
        if self.app_env == "production":
            if self.operator_panel_access_mode == "public":
                raise ValueError(
                    "Public production panel access is unsupported until application MFA is implemented"
                )
            if not self.restricted_panel_mfa_risk_accepted:
                raise ValueError(
                    "Restricted production access without MFA requires documented risk acceptance"
                )
            if self.api_docs_enabled:
                raise ValueError("Interactive API documentation must be disabled in production")
            if any(not origin.startswith("https://") for origin in self.browser_origins):
                raise ValueError("Production browser origins must use HTTPS")
            if "local-development-only" in self.database_url:
                raise ValueError("Production database credentials must not use local defaults")
        if self.whatsapp_provider == "meta":
            if self.whatsapp_secret_file is None:
                raise ValueError("Meta WhatsApp requires a deployment secret file")
            if not self.meta_graph_api_version:
                raise ValueError("Meta WhatsApp requires an explicit Graph API version")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
