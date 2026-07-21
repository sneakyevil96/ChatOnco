from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
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
    database_url: str = (
        "postgresql+psycopg://screening_local:local-development-only@localhost:5432/"
        "screening_platform"
    )
    project_config_dir: Path = default_project_config_dir()
    whatsapp_provider: Literal["mock"] = "mock"
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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
