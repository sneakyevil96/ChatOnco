import argparse
import asyncio
from uuid import uuid4

from app.core.project_config import ProjectCatalog, ProjectId
from app.core.settings import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.services.ticket_workflow import escalate_inbound_text


async def create_synthetic_ticket(project_id: ProjectId, message: str) -> tuple[str, str]:
    settings = get_settings()
    if settings.app_env not in {"local", "test"}:
        raise RuntimeError("Synthetic tickets are allowed only in local or test environments")
    catalog = ProjectCatalog.load(settings.project_config_dir)
    catalog.get(project_id)
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    synthetic_id = uuid4().hex
    try:
        async with session_factory.begin() as database:
            result = await escalate_inbound_text(
                database,
                project_id=project_id.value,
                whatsapp_user_id=f"synthetic-{synthetic_id}",
                phone_number_e164=f"+40700{int(synthetic_id[:8], 16) % 1_000_000:06d}",
                text=message,
                meta_message_id=f"synthetic-{synthetic_id}",
            )
            return str(result.ticket.id), result.ticket.reference
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create one synthetic local ticket without contacting WhatsApp."
    )
    parser.add_argument("--project", required=True, choices=[item.value for item in ProjectId])
    parser.add_argument(
        "--message",
        default="Întrebare administrativă sintetică pentru verificarea fluxului de suport.",
    )
    arguments = parser.parse_args()
    ticket_id, reference = asyncio.run(
        create_synthetic_ticket(ProjectId(arguments.project), arguments.message)
    )
    print(f"Synthetic ticket created: {reference} ({ticket_id})")


if __name__ == "__main__":
    main()
