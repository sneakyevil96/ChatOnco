from functools import lru_cache
from pathlib import Path
from typing import Literal

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


@lru_cache
def get_settings() -> Settings:
    return Settings()

