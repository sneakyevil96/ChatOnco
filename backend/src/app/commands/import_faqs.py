import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select

from app.core.project_config import ProjectCatalog, ProjectId
from app.core.settings import get_settings
from app.db.models.auth import OperatorAccount, OperatorProjectMembership
from app.db.models.enums import OperatorRole
from app.db.session import create_database_engine, create_session_factory
from app.services.faq_embeddings import SentenceTransformerEmbeddingProvider
from app.services.faq_import import import_faq_csv, parse_faq_csv


async def import_approved_file(
    project_id: ProjectId,
    administrator_email: str | None,
    path: Path,
    *,
    publish: bool,
    with_embeddings: bool,
) -> None:
    content = path.read_bytes()
    rows = parse_faq_csv(content)
    if not publish:
        print(f"Validation successful: {len(rows)} FAQ rows. No database changes were made.")
        return

    settings = get_settings()
    catalog = ProjectCatalog.load(settings.project_config_dir)
    project = catalog.get(project_id)
    if not administrator_email:
        raise RuntimeError("--administrator-email is required when --publish is used")
    if project.faq_retrieval.semantic_enabled and not with_embeddings:
        raise RuntimeError("Semantic retrieval is enabled; the published import requires embeddings")
    embedder = (
        SentenceTransformerEmbeddingProvider(project.faq_retrieval.embedding_model)
        if with_embeddings
        else None
    )
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory.begin() as database:
            row = (
                await database.execute(
                    select(OperatorAccount, OperatorProjectMembership)
                    .join(
                        OperatorProjectMembership,
                        OperatorProjectMembership.operator_account_id == OperatorAccount.id,
                    )
                    .where(
                        OperatorAccount.email == administrator_email.strip().casefold(),
                        OperatorAccount.disabled_at.is_(None),
                        OperatorProjectMembership.project_id == project_id.value,
                        OperatorProjectMembership.role == OperatorRole.ADMINISTRATOR,
                        OperatorProjectMembership.is_active.is_(True),
                    )
                )
            ).one_or_none()
            if row is None:
                raise RuntimeError("An active project administrator account is required")
            result = await import_faq_csv(
                database,
                project_id=project_id.value,
                source_filename=path.name,
                content=content,
                administrator_account_id=row[0].id,
                administrator_membership_id=row[1].id,
                publish=True,
                embedding_provider=embedder,
            )
        print(
            f"Published {len(result.imported_versions)} FAQ versions in batch {result.batch_id}."
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate or publish an approved project-scoped FAQ CSV file."
    )
    parser.add_argument("--project", required=True, choices=[item.value for item in ProjectId])
    parser.add_argument("--administrator-email")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Persist and publish the validated versions; without this flag validation is read-only.",
    )
    parser.add_argument(
        "--with-embeddings",
        action="store_true",
        help="Generate local sentence-transformer embeddings during publication.",
    )
    arguments = parser.parse_args()
    asyncio.run(
        import_approved_file(
            ProjectId(arguments.project),
            arguments.administrator_email,
            arguments.file,
            publish=arguments.publish,
            with_embeddings=arguments.with_embeddings,
        )
    )


if __name__ == "__main__":
    main()
