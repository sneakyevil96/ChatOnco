import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectId(StrEnum):
    ONCODIR = "ONCODIR"
    ONCOSCREEN = "ONCOSCREEN"


class BrandingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    logo_url: str | None = None


class MessageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fallback: str = Field(min_length=1)
    privacy_warning: str = Field(min_length=1)
    unsupported_message: str = Field(min_length=1)


class RetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_content_days: int = Field(default=90, ge=1)
    tickets_and_notes_days: int = Field(default=365, ge=1)
    audit_events_days: int = Field(default=730, ge=1)
    application_logs_days: int = Field(default=90, ge=1)
    backups_days: int = Field(default=30, ge=1)
    privacy_warning_inactivity_days: int = Field(default=30, ge=1)
    resolved_ticket_reopen_days: int = Field(default=7, ge=0)


class WhatsAppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    phone_number_id: str | None = None
    credential_binding: str | None = None
    templates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_bindings_when_enabled(self) -> "WhatsAppConfig":
        if self.enabled and (not self.phone_number_id or not self.credential_binding):
            raise ValueError(
                "Enabled WhatsApp configuration requires a phone number ID and credential binding"
            )
        return self


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: ProjectId
    public_name: str = Field(min_length=1)
    content_status: str = "development_placeholder"
    faq_collection_key: str = Field(min_length=1)
    contact_information: str | None = None
    branding: BrandingConfig
    messages: MessageConfig
    retention: RetentionConfig
    whatsapp: WhatsAppConfig


class ProjectCatalog:
    def __init__(self, projects: dict[ProjectId, ProjectConfig]) -> None:
        self._projects = projects

    @classmethod
    def load(cls, directory: Path) -> "ProjectCatalog":
        if not directory.is_dir():
            raise ValueError(f"Project configuration directory does not exist: {directory}")

        projects: dict[ProjectId, ProjectConfig] = {}
        for path in sorted(directory.glob("*.json")):
            project = ProjectConfig.model_validate_json(path.read_text(encoding="utf-8"))
            if path.stem != project.project_id.value:
                raise ValueError(
                    f"Project configuration filename {path.name} does not match {project.project_id}"
                )
            if project.project_id in projects:
                raise ValueError(f"Duplicate project configuration: {project.project_id}")
            projects[project.project_id] = project

        missing = set(ProjectId) - set(projects)
        if missing:
            missing_names = ", ".join(sorted(project.value for project in missing))
            raise ValueError(f"Missing required project configuration: {missing_names}")
        return cls(projects)

    def get(self, project_id: ProjectId) -> ProjectConfig:
        return self._projects[project_id]

    def all(self) -> tuple[ProjectConfig, ...]:
        return tuple(self._projects[project_id] for project_id in ProjectId)

