import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

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


class WhatsAppTemplateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=512)
    language_code: str = Field(default="ro", min_length=2, max_length=16)
    purpose: str = Field(min_length=1, max_length=160)
    status: Literal["draft", "submitted", "approved", "rejected", "paused"] = "draft"
    approved_body_snapshot: str | None = None
    body_parameter_count: int = Field(default=0, ge=0, le=20)

    @model_validator(mode="after")
    def require_snapshot_for_approved_template(self) -> "WhatsAppTemplateConfig":
        if self.status == "approved" and not self.approved_body_snapshot:
            raise ValueError("Approved WhatsApp templates require an approved body snapshot")
        return self


class WhatsAppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    phone_number_id: str | None = None
    credential_binding: str | None = None
    webhook_binding: str | None = None
    unsupported_warning_cooldown_minutes: int = Field(default=10, ge=1, le=1440)
    interactive_actions: dict[str, str] = Field(default_factory=dict)
    templates: list[WhatsAppTemplateConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_bindings_when_enabled(self) -> "WhatsAppConfig":
        if self.enabled and (
            not self.phone_number_id
            or not self.credential_binding
            or not self.webhook_binding
        ):
            raise ValueError(
                "Enabled WhatsApp configuration requires phone, credential, and webhook bindings"
            )
        template_keys = [
            (template.name, template.language_code) for template in self.templates
        ]
        if len(template_keys) != len(set(template_keys)):
            raise ValueError("WhatsApp template names and languages must be unique per project")
        if any(not action_id.strip() or not text.strip() for action_id, text in self.interactive_actions.items()):
            raise ValueError("WhatsApp interactive action IDs and mapped text must not be empty")
        return self


class FaqRetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    semantic_enabled: bool = False
    semantic_threshold: float | None = Field(default=None, ge=-1, le=1)
    minimum_score_gap: float | None = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def require_calibrated_thresholds_when_enabled(self) -> "FaqRetrievalConfig":
        if self.semantic_enabled and (
            self.semantic_threshold is None or self.minimum_score_gap is None
        ):
            raise ValueError(
                "Semantic FAQ retrieval requires a calibrated threshold and score gap"
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
    faq_retrieval: FaqRetrievalConfig
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

    def by_phone_number_id(self, phone_number_id: str) -> ProjectConfig | None:
        matches = [
            project
            for project in self.all()
            if project.whatsapp.enabled
            and project.whatsapp.phone_number_id == phone_number_id
        ]
        if len(matches) > 1:
            raise RuntimeError("A WhatsApp phone-number ID is bound to multiple projects")
        return matches[0] if matches else None
