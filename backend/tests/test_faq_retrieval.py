import asyncio
import csv
import io
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytest.importorskip("pgvector")

from app.core.project_config import FaqRetrievalConfig, ProjectCatalog, ProjectId
from app.core.settings import get_settings
from app.db.models.audit import AuditEvent
from app.db.models.auth import OperatorAccount, OperatorProjectMembership
from app.db.models.enums import FaqPublicationStatus, OperatorRole
from app.db.models.faq import FaqItem, FaqVersion
from app.db.models.conversation import Ticket, WhatsAppMessage
from app.db.models.outbox import OutboxEntry
from app.db.session import create_database_engine
from app.services.faq_evaluation import (
    FaqEvaluationItem,
    evaluate_faq_retrieval,
    parse_evaluation_csv,
)
from app.services.faq_import import (
    FaqImportValidationError,
    expire_due_faq_versions,
    import_faq_csv,
    parse_faq_csv,
    retire_published_faq,
)
from app.services.faq_normalization import normalize_romanian_question
from app.services.faq_retrieval import FaqRetrievalOutcome, retrieve_approved_faq
from app.services.inbound_orchestration import InboundOutcome, handle_inbound_text


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="PostgreSQL integration tests are disabled",
)

FAQ_COLUMNS = [
    "logical_key",
    "version_number",
    "approved_answer_ro",
    "approved_answer_en",
    "alternative_questions_ro",
    "administrative_reviewer_reference",
    "clinical_reviewer_reference",
    "reviewed_at",
    "valid_from",
    "valid_until",
    "requires_clinical_review",
]


class SyntheticEmbeddingProvider:
    model_name = "synthetic-multilingual-384"
    dimension = 384

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]


def vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * 382)]


def faq_csv(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FAQ_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def faq_row(
    logical_key: str,
    version: int,
    answer: str,
    questions: str,
    *,
    requires_clinical_review: str = "false",
    clinical_reviewer: str = "",
    valid_until: str = "",
) -> dict[str, str]:
    return {
        "logical_key": logical_key,
        "version_number": str(version),
        "approved_answer_ro": answer,
        "approved_answer_en": "",
        "alternative_questions_ro": questions,
        "administrative_reviewer_reference": "project-lead-role",
        "clinical_reviewer_reference": clinical_reviewer,
        "reviewed_at": "2026-07-21T10:00:00+03:00",
        "valid_from": "",
        "valid_until": valid_until,
        "requires_clinical_review": requires_clinical_review,
    }


async def create_admin(database: AsyncSession, project_id: str) -> tuple[OperatorAccount, OperatorProjectMembership]:
    account = OperatorAccount(
        email=f"phase5-{project_id.casefold()}@example.invalid",
        password_hash="synthetic-not-used",
        must_change_password=False,
    )
    database.add(account)
    await database.flush()
    membership = OperatorProjectMembership(
        project_id=project_id,
        operator_account_id=account.id,
        role=OperatorRole.ADMINISTRATOR,
        is_active=True,
    )
    database.add(membership)
    await database.flush()
    return account, membership


def test_romanian_normalization_handles_diacritics_and_punctuation() -> None:
    assert normalize_romanian_question("  Unde trebuie să merg? ") == "unde trebuie sa merg"
    assert normalize_romanian_question("UNDE trebuie sa merg!!!") == "unde trebuie sa merg"
    assert normalize_romanian_question("Cine mă poate ajuta?") == "cine ma poate ajuta"


def test_import_validation_requires_clinical_review_when_flagged() -> None:
    content = faq_csv(
        [
            faq_row(
                "medical-adjacent",
                1,
                "Răspuns aprobat sintetic.",
                "Întrebare sintetică?",
                requires_clinical_review="true",
            )
        ]
    )
    with pytest.raises(FaqImportValidationError, match="clinical reviewer is required"):
        parse_faq_csv(content)


def test_evaluation_csv_requires_version_or_escalate_labels() -> None:
    valid = (
        "question_ro,expected,high_risk\n"
        "Întrebare exactă,location@1,false\n"
        "Întrebare necunoscută,ESCALATE,true\n"
    ).encode()
    assert len(parse_evaluation_csv(valid)) == 2
    invalid = "question_ro,expected,high_risk\nÎntrebare,location,false\n".encode()
    with pytest.raises(FaqImportValidationError, match="logical_key@version"):
        parse_evaluation_csv(invalid)


def test_exact_retrieval_is_project_scoped_and_returns_the_stored_answer_verbatim() -> None:
    async def scenario() -> None:
        engine = create_database_engine(os.environ["DATABASE_URL"])
        async with engine.connect() as connection:
            transaction = await connection.begin()
            database = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                account, membership = await create_admin(database, "ONCODIR")
                answer = "Răspuns aprobat, păstrat exact — inclusiv punctuația."
                result = await import_faq_csv(
                    database,
                    project_id="ONCODIR",
                    source_filename="synthetic-exact.csv",
                    content=faq_csv(
                        [faq_row("location", 1, answer, "Unde trebuie să merg?||Care este locația?")]
                    ),
                    administrator_account_id=account.id,
                    administrator_membership_id=membership.id,
                    publish=True,
                )
                assert result.published is True

                configuration = FaqRetrievalConfig(
                    embedding_model="synthetic-multilingual-384",
                    semantic_enabled=False,
                )
                match = await retrieve_approved_faq(
                    database,
                    project_id="ONCODIR",
                    question="UNDE trebuie sa merg!!!",
                    configuration=configuration,
                )
                assert match.outcome == FaqRetrievalOutcome.MATCH
                assert match.match_kind == "exact"
                assert match.approved_answer == answer
                assert match.faq_label == "location@1"

                other_project = await retrieve_approved_faq(
                    database,
                    project_id="ONCOSCREEN",
                    question="Unde trebuie să merg?",
                    configuration=configuration,
                )
                assert other_project.outcome == FaqRetrievalOutcome.ESCALATE
                assert other_project.reason == "semantic_retrieval_disabled"

                version_id = await retire_published_faq(
                    database,
                    project_id="ONCODIR",
                    logical_key="location",
                    reason="Retragere sintetică de urgență",
                    administrator_account_id=account.id,
                    administrator_membership_id=membership.id,
                )
                after_retirement = await retrieve_approved_faq(
                    database,
                    project_id="ONCODIR",
                    question="Unde trebuie să merg?",
                    configuration=configuration,
                )
                assert after_retirement.outcome == FaqRetrievalOutcome.ESCALATE
                event = await database.scalar(
                    select(AuditEvent).where(
                        AuditEvent.action == "faq.emergency_withdrawal",
                        AuditEvent.target_id == str(version_id),
                    )
                )
                assert event is not None
                assert event.project_id == "ONCODIR"
            finally:
                await database.close()
                await transaction.rollback()
        await engine.dispose()

    asyncio.run(scenario())


def test_publishing_a_replacement_retires_the_previous_version() -> None:
    async def scenario() -> None:
        engine = create_database_engine(os.environ["DATABASE_URL"])
        async with engine.connect() as connection:
            transaction = await connection.begin()
            database = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                account, membership = await create_admin(database, "ONCODIR")
                for version_number in (1, 2):
                    await import_faq_csv(
                        database,
                        project_id="ONCODIR",
                        source_filename=f"synthetic-v{version_number}.csv",
                        content=faq_csv(
                            [
                                faq_row(
                                    "documents",
                                    version_number,
                                    f"Răspuns aprobat versiunea {version_number}.",
                                    f"Ce documente sunt necesare în versiunea {version_number}?",
                                )
                            ]
                        ),
                        administrator_account_id=account.id,
                        administrator_membership_id=membership.id,
                        publish=True,
                    )
                versions = list(
                    await database.scalars(
                        select(FaqVersion)
                        .join(
                            FaqItem,
                            (FaqItem.project_id == FaqVersion.project_id)
                            & (FaqItem.id == FaqVersion.faq_item_id),
                        )
                        .where(
                            FaqVersion.project_id == "ONCODIR",
                            FaqItem.logical_key == "documents",
                        )
                        .order_by(FaqVersion.version_number)
                    )
                )
                assert [version.publication_status for version in versions] == [
                    FaqPublicationStatus.RETIRED,
                    FaqPublicationStatus.PUBLISHED,
                ]
                assert versions[0].retirement_reason == "Replaced by version 2"
            finally:
                await database.close()
                await transaction.rollback()
        await engine.dispose()

    asyncio.run(scenario())


def test_semantic_retrieval_enforces_threshold_and_best_second_gap() -> None:
    async def scenario() -> None:
        engine = create_database_engine(os.environ["DATABASE_URL"])
        async with engine.connect() as connection:
            transaction = await connection.begin()
            database = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                account, membership = await create_admin(database, "ONCOSCREEN")
                question_a = "Unde este locația sintetică?"
                question_b = "Ce document sintetic este necesar?"
                provider = SyntheticEmbeddingProvider(
                    {
                        question_a: vector(1.0, 0.0),
                        question_b: vector(0.0, 1.0),
                        "parafrază clară": vector(1.0, 0.0),
                        "parafrază ambiguă": vector(2 ** -0.5, 2 ** -0.5),
                        "risc": vector(1.0, 0.0),
                    }
                )
                await import_faq_csv(
                    database,
                    project_id="ONCOSCREEN",
                    source_filename="synthetic-semantic.csv",
                    content=faq_csv(
                        [
                            faq_row("location", 1, "Locația aprobată sintetic.", question_a),
                            faq_row("documents", 1, "Documentul aprobat sintetic.", question_b),
                        ]
                    ),
                    administrator_account_id=account.id,
                    administrator_membership_id=membership.id,
                    publish=True,
                    embedding_provider=provider,
                )
                configuration = FaqRetrievalConfig(
                    embedding_model=provider.model_name,
                    semantic_enabled=True,
                    semantic_threshold=0.7,
                    minimum_score_gap=0.1,
                )
                clear = await retrieve_approved_faq(
                    database,
                    project_id="ONCOSCREEN",
                    question="parafrază clară",
                    configuration=configuration,
                    embedding_provider=provider,
                )
                assert clear.outcome == FaqRetrievalOutcome.MATCH
                assert clear.faq_label == "location@1"
                assert clear.approved_answer == "Locația aprobată sintetic."

                ambiguous = await retrieve_approved_faq(
                    database,
                    project_id="ONCOSCREEN",
                    question="parafrază ambiguă",
                    configuration=configuration,
                    embedding_provider=provider,
                )
                assert ambiguous.outcome == FaqRetrievalOutcome.ESCALATE
                assert ambiguous.reason == "ambiguous_semantic_match"

                metrics = await evaluate_faq_retrieval(
                    database,
                    project_id="ONCOSCREEN",
                    items=(
                        FaqEvaluationItem("parafrază clară", "location@1", False),
                        FaqEvaluationItem("parafrază ambiguă", "ESCALATE", True),
                        FaqEvaluationItem("risc", "documents@1", True),
                    ),
                    configuration=configuration,
                    embedding_provider=provider,
                )
                assert metrics.correct_automatic_answers == 1
                assert metrics.incorrect_automatic_answers == 1
                assert metrics.high_risk_incorrect_automatic_answers == 1
                assert metrics.meets_safety_targets is False
            finally:
                await database.close()
                await transaction.rollback()
        await engine.dispose()

    asyncio.run(scenario())


def test_expired_published_content_is_never_returned() -> None:
    async def scenario() -> None:
        engine = create_database_engine(os.environ["DATABASE_URL"])
        async with engine.connect() as connection:
            transaction = await connection.begin()
            database = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                account, membership = await create_admin(database, "ONCODIR")
                yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
                await import_faq_csv(
                    database,
                    project_id="ONCODIR",
                    source_filename="synthetic-expired.csv",
                    content=faq_csv(
                        [
                            faq_row(
                                "expired",
                                1,
                                "Acest răspuns nu trebuie returnat.",
                                "Întrebare expirată?",
                                valid_until=yesterday,
                            )
                        ]
                    ),
                    administrator_account_id=account.id,
                    administrator_membership_id=membership.id,
                    publish=True,
                )
                result = await retrieve_approved_faq(
                    database,
                    project_id="ONCODIR",
                    question="Întrebare expirată?",
                    configuration=FaqRetrievalConfig(
                        embedding_model="synthetic-multilingual-384",
                        semantic_enabled=False,
                    ),
                )
                assert result.outcome == FaqRetrievalOutcome.ESCALATE
                expired_ids = await expire_due_faq_versions(
                    database,
                    project_id="ONCODIR",
                )
                assert len(expired_ids) == 1
                expired = await database.get(FaqVersion, expired_ids[0])
                assert expired is not None
                assert expired.publication_status == FaqPublicationStatus.EXPIRED
                assert await database.scalar(
                    select(AuditEvent).where(
                        AuditEvent.action == "faq.version_expired",
                        AuditEvent.target_id == str(expired.id),
                    )
                )
            finally:
                await database.close()
                await transaction.rollback()
        await engine.dispose()

    asyncio.run(scenario())


def test_inbound_orchestration_answers_exact_faqs_and_escalates_unknowns_once() -> None:
    async def scenario() -> None:
        engine = create_database_engine(os.environ["DATABASE_URL"])
        async with engine.connect() as connection:
            transaction = await connection.begin()
            database = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                project = ProjectCatalog.load(get_settings().project_config_dir).get(
                    ProjectId.ONCODIR
                )
                account, membership = await create_admin(database, "ONCODIR")
                approved_answer = "Răspunsul administrativ aprobat exact."
                await import_faq_csv(
                    database,
                    project_id="ONCODIR",
                    source_filename="synthetic-orchestration.csv",
                    content=faq_csv(
                        [
                            faq_row(
                                "orchestration",
                                1,
                                approved_answer,
                                "Unde este punctul administrativ?",
                            )
                        ]
                    ),
                    administrator_account_id=account.id,
                    administrator_membership_id=membership.id,
                    publish=True,
                )

                answered = await handle_inbound_text(
                    database,
                    project=project,
                    whatsapp_user_id="phase5-faq-user",
                    phone_number_e164="+40700000501",
                    text="Unde este punctul administrativ?",
                    meta_message_id="phase5-faq-message",
                )
                assert answered.outcome == InboundOutcome.FAQ_ANSWER
                assert answered.ticket_id is None
                outbound = await database.get(WhatsAppMessage, answered.outbound_message_id)
                assert outbound is not None
                assert outbound.text_content == approved_answer
                assert await database.scalar(
                    select(OutboxEntry.id).where(OutboxEntry.message_id == outbound.id)
                )

                escalated = await handle_inbound_text(
                    database,
                    project=project,
                    whatsapp_user_id="phase5-unknown-user",
                    phone_number_e164="+40700000502",
                    text="Întrebare complet necunoscută.",
                    meta_message_id="phase5-unknown-message",
                )
                assert escalated.outcome == InboundOutcome.HUMAN_SUPPORT
                assert escalated.ticket_id is not None
                fallback = await database.get(WhatsAppMessage, escalated.outbound_message_id)
                assert fallback is not None
                assert fallback.text_content == project.messages.fallback
                ticket = await database.get(Ticket, escalated.ticket_id)
                assert ticket is not None
                assert ticket.status.value == "NEW"

                active_bypass = await handle_inbound_text(
                    database,
                    project=project,
                    whatsapp_user_id="phase5-unknown-user",
                    text="Unde este punctul administrativ?",
                    meta_message_id="phase5-active-bypass",
                )
                assert active_bypass.outcome == InboundOutcome.HUMAN_SUPPORT
                assert active_bypass.ticket_id == escalated.ticket_id
                assert active_bypass.outbound_message_id is None

                before_duplicate = await database.scalar(
                    select(func.count(WhatsAppMessage.id)).where(
                        WhatsAppMessage.project_id == "ONCODIR"
                    )
                )
                duplicate = await handle_inbound_text(
                    database,
                    project=project,
                    whatsapp_user_id="phase5-unknown-user",
                    text="Mesaj duplicat care nu trebuie persistat.",
                    meta_message_id="phase5-active-bypass",
                )
                assert duplicate.outcome == InboundOutcome.DUPLICATE
                after_duplicate = await database.scalar(
                    select(func.count(WhatsAppMessage.id)).where(
                        WhatsAppMessage.project_id == "ONCODIR"
                    )
                )
                assert after_duplicate == before_duplicate
            finally:
                await database.close()
                await transaction.rollback()
        await engine.dispose()

    asyncio.run(scenario())
