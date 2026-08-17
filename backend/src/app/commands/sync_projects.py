import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.project_config import ProjectCatalog, ProjectConfig
from app.core.settings import get_settings
from app.db.models.project import Project, RetentionPolicy
from app.db.models.enums import TemplateStatus
from app.db.models.whatsapp import ProjectWhatsAppConfiguration, WhatsAppTemplate
from app.db.session import create_database_engine, create_session_factory


def retention_values(project: ProjectConfig) -> dict[str, int]:
    retention = project.retention
    return {
        "message_content_days": retention.message_content_days,
        "tickets_and_notes_days": retention.tickets_and_notes_days,
        "audit_events_days": retention.audit_events_days,
        "application_logs_days": retention.application_logs_days,
        "backups_days": retention.backups_days,
        "privacy_warning_inactivity_days": retention.privacy_warning_inactivity_days,
        "resolved_ticket_reopen_days": retention.resolved_ticket_reopen_days,
    }


async def synchronize_projects() -> None:
    settings = get_settings()
    catalog = ProjectCatalog.load(settings.project_config_dir)
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory.begin() as session:
            for configured_project in catalog.all():
                project_id = configured_project.project_id.value
                project_statement = insert(Project).values(
                    id=project_id,
                    public_name=configured_project.public_name,
                    content_status=configured_project.content_status,
                    is_enabled=True,
                )
                project_statement = project_statement.on_conflict_do_update(
                    index_elements=[Project.id],
                    set_={
                        "public_name": configured_project.public_name,
                        "content_status": configured_project.content_status,
                        "is_enabled": True,
                        "updated_at": func.now(),
                    },
                )
                await session.execute(project_statement)

                whatsapp = configured_project.whatsapp
                whatsapp_statement = insert(ProjectWhatsAppConfiguration).values(
                    project_id=project_id,
                    is_enabled=whatsapp.enabled,
                    display_phone_number=whatsapp.display_phone_number,
                    phone_number_id=whatsapp.phone_number_id,
                    waba_id=whatsapp.waba_id,
                    credential_binding=whatsapp.credential_binding,
                    webhook_binding=whatsapp.webhook_binding,
                )
                whatsapp_statement = whatsapp_statement.on_conflict_do_update(
                    index_elements=[ProjectWhatsAppConfiguration.project_id],
                    set_={
                        "is_enabled": whatsapp.enabled,
                        "display_phone_number": whatsapp.display_phone_number,
                        "phone_number_id": whatsapp.phone_number_id,
                        "waba_id": whatsapp.waba_id,
                        "credential_binding": whatsapp.credential_binding,
                        "webhook_binding": whatsapp.webhook_binding,
                        "updated_at": func.now(),
                    },
                )
                await session.execute(whatsapp_statement)

                for configured_template in whatsapp.templates:
                    template_statement = insert(WhatsAppTemplate).values(
                        project_id=project_id,
                        template_name=configured_template.name,
                        language_code=configured_template.language_code,
                        purpose=configured_template.purpose,
                        status=TemplateStatus(configured_template.status),
                        approved_body_snapshot=configured_template.approved_body_snapshot,
                        variables_schema={
                            "body_parameter_count": configured_template.body_parameter_count
                        },
                    )
                    template_statement = template_statement.on_conflict_do_update(
                        index_elements=[
                            WhatsAppTemplate.project_id,
                            WhatsAppTemplate.template_name,
                            WhatsAppTemplate.language_code,
                        ],
                        set_={
                            "purpose": configured_template.purpose,
                            "status": TemplateStatus(configured_template.status),
                            "approved_body_snapshot": configured_template.approved_body_snapshot,
                            "variables_schema": {
                                "body_parameter_count": configured_template.body_parameter_count
                            },
                            "retired_at": None,
                            "updated_at": func.now(),
                        },
                    )
                    await session.execute(template_statement)

                configured_template_keys = {
                    (template.name, template.language_code)
                    for template in whatsapp.templates
                }
                stored_templates = (
                    await session.scalars(
                        select(WhatsAppTemplate).where(
                            WhatsAppTemplate.project_id == project_id,
                            WhatsAppTemplate.retired_at.is_(None),
                        )
                    )
                ).all()
                for stored_template in stored_templates:
                    key = (stored_template.template_name, stored_template.language_code)
                    if key not in configured_template_keys:
                        stored_template.status = TemplateStatus.PAUSED
                        stored_template.retired_at = datetime.now(UTC)

                configured_retention = retention_values(configured_project)
                current = await session.scalar(
                    select(RetentionPolicy)
                    .where(
                        RetentionPolicy.project_id == project_id,
                        RetentionPolicy.is_current.is_(True),
                    )
                    .order_by(RetentionPolicy.version.desc())
                    .limit(1)
                )
                if current is None:
                    session.add(
                        RetentionPolicy(
                            project_id=project_id,
                            version=1,
                            is_current=True,
                            **configured_retention,
                        )
                    )
                elif any(
                    getattr(current, field) != value
                    for field, value in configured_retention.items()
                ):
                    await session.execute(
                        update(RetentionPolicy)
                        .where(
                            RetentionPolicy.project_id == project_id,
                            RetentionPolicy.is_current.is_(True),
                        )
                        .values(is_current=False, updated_at=func.now())
                    )
                    latest_version = await session.scalar(
                        select(func.max(RetentionPolicy.version)).where(
                            RetentionPolicy.project_id == project_id
                        )
                    )
                    session.add(
                        RetentionPolicy(
                            project_id=project_id,
                            version=(latest_version or 0) + 1,
                            is_current=True,
                            **configured_retention,
                        )
                    )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(synchronize_projects())
