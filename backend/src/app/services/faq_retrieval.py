from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.project_config import FaqRetrievalConfig
from app.db.models.enums import FaqPublicationStatus
from app.db.models.faq import FaqAlternativeQuestion, FaqItem, FaqVersion
from app.services.faq_embeddings import EmbeddingProvider
from app.services.faq_normalization import normalize_romanian_question


class FaqRetrievalOutcome(StrEnum):
    MATCH = "MATCH"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True, slots=True)
class FaqRetrievalResult:
    outcome: FaqRetrievalOutcome
    reason: str
    approved_answer: str | None = None
    faq_version_id: UUID | None = None
    faq_label: str | None = None
    score: float | None = None
    score_gap: float | None = None
    match_kind: str | None = None


def valid_published_version_conditions(project_id: str, now: datetime):
    return (
        FaqVersion.project_id == project_id,
        FaqVersion.publication_status == FaqPublicationStatus.PUBLISHED,
        or_(FaqVersion.valid_from.is_(None), FaqVersion.valid_from <= now),
        or_(FaqVersion.valid_until.is_(None), FaqVersion.valid_until >= now),
    )


async def retrieve_approved_faq(
    database: AsyncSession,
    *,
    project_id: str,
    question: str,
    configuration: FaqRetrievalConfig,
    embedding_provider: EmbeddingProvider | None = None,
    now: datetime | None = None,
) -> FaqRetrievalResult:
    current_time = now or datetime.now(UTC)
    normalized = normalize_romanian_question(question)
    if not normalized:
        return FaqRetrievalResult(
            outcome=FaqRetrievalOutcome.ESCALATE,
            reason="empty_normalized_question",
        )

    exact_rows = (
        await database.execute(
            select(FaqVersion, FaqItem.logical_key)
            .join(
                FaqAlternativeQuestion,
                (FaqAlternativeQuestion.project_id == FaqVersion.project_id)
                & (FaqAlternativeQuestion.faq_version_id == FaqVersion.id),
            )
            .join(
                FaqItem,
                (FaqItem.project_id == FaqVersion.project_id)
                & (FaqItem.id == FaqVersion.faq_item_id),
            )
            .where(
                *valid_published_version_conditions(project_id, current_time),
                FaqAlternativeQuestion.normalized_question == normalized,
            )
        )
    ).all()
    exact_versions = {version.id: (version, logical_key) for version, logical_key in exact_rows}
    if len(exact_versions) == 1:
        version, logical_key = next(iter(exact_versions.values()))
        return FaqRetrievalResult(
            outcome=FaqRetrievalOutcome.MATCH,
            reason="exact_match",
            approved_answer=version.approved_answer_ro,
            faq_version_id=version.id,
            faq_label=f"{logical_key}@{version.version_number}",
            score=1.0,
            match_kind="exact",
        )
    if len(exact_versions) > 1:
        return FaqRetrievalResult(
            outcome=FaqRetrievalOutcome.ESCALATE,
            reason="ambiguous_exact_match",
        )

    if not configuration.semantic_enabled:
        return FaqRetrievalResult(
            outcome=FaqRetrievalOutcome.ESCALATE,
            reason="semantic_retrieval_disabled",
        )
    if (
        configuration.semantic_threshold is None
        or configuration.minimum_score_gap is None
        or embedding_provider is None
    ):
        return FaqRetrievalResult(
            outcome=FaqRetrievalOutcome.ESCALATE,
            reason="semantic_retrieval_not_calibrated",
        )
    if embedding_provider.model_name != configuration.embedding_model:
        return FaqRetrievalResult(
            outcome=FaqRetrievalOutcome.ESCALATE,
            reason="embedding_model_mismatch",
        )

    query_vectors = embedding_provider.embed([question])
    if len(query_vectors) != 1 or len(query_vectors[0]) != 384:
        return FaqRetrievalResult(
            outcome=FaqRetrievalOutcome.ESCALATE,
            reason="invalid_query_embedding",
        )
    distance = FaqAlternativeQuestion.embedding.cosine_distance(query_vectors[0])
    rows = (
        await database.execute(
            select(FaqVersion, FaqItem.logical_key, distance.label("distance"))
            .join(
                FaqAlternativeQuestion,
                (FaqAlternativeQuestion.project_id == FaqVersion.project_id)
                & (FaqAlternativeQuestion.faq_version_id == FaqVersion.id),
            )
            .join(
                FaqItem,
                (FaqItem.project_id == FaqVersion.project_id)
                & (FaqItem.id == FaqVersion.faq_item_id),
            )
            .where(
                *valid_published_version_conditions(project_id, current_time),
                FaqAlternativeQuestion.embedding.is_not(None),
                FaqAlternativeQuestion.embedding_model == configuration.embedding_model,
            )
            .order_by(distance)
            .limit(50)
        )
    ).all()
    best_by_version: dict[UUID, tuple[FaqVersion, str, float]] = {}
    for version, logical_key, vector_distance in rows:
        score = 1.0 - float(vector_distance)
        previous = best_by_version.get(version.id)
        if previous is None or score > previous[2]:
            best_by_version[version.id] = (version, logical_key, score)
    ranked = sorted(best_by_version.values(), key=lambda item: item[2], reverse=True)
    if not ranked:
        return FaqRetrievalResult(
            outcome=FaqRetrievalOutcome.ESCALATE,
            reason="no_semantic_candidates",
        )

    best_version, best_key, best_score = ranked[0]
    second_score = ranked[1][2] if len(ranked) > 1 else -1.0
    gap = best_score - second_score
    if best_score < configuration.semantic_threshold:
        return FaqRetrievalResult(
            outcome=FaqRetrievalOutcome.ESCALATE,
            reason="score_below_threshold",
            score=best_score,
            score_gap=gap,
        )
    if gap < configuration.minimum_score_gap:
        return FaqRetrievalResult(
            outcome=FaqRetrievalOutcome.ESCALATE,
            reason="ambiguous_semantic_match",
            score=best_score,
            score_gap=gap,
        )
    return FaqRetrievalResult(
        outcome=FaqRetrievalOutcome.MATCH,
        reason="semantic_match",
        approved_answer=best_version.approved_answer_ro,
        faq_version_id=best_version.id,
        faq_label=f"{best_key}@{best_version.version_number}",
        score=best_score,
        score_gap=gap,
        match_kind="semantic",
    )
