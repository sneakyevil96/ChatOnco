import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import FaqPublicationStatus
from app.db.models.faq import (
    FaqAlternativeQuestion,
    FaqImportBatch,
    FaqItem,
    FaqVersion,
)
from app.services.audit import record_audit_event
from app.services.faq_embeddings import EmbeddingProvider
from app.services.faq_normalization import normalize_romanian_question


REQUIRED_COLUMNS = {
    "logical_key",
    "version_number",
    "approved_answer_ro",
    "alternative_questions_ro",
    "administrative_reviewer_reference",
    "reviewed_at",
    "requires_clinical_review",
}
OPTIONAL_COLUMNS = {
    "approved_answer_en",
    "clinical_reviewer_reference",
    "valid_from",
    "valid_until",
}


class FaqImportValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True, slots=True)
class FaqImportRow:
    logical_key: str
    version_number: int
    approved_answer_ro: str
    approved_answer_en: str | None
    alternative_questions_ro: tuple[str, ...]
    administrative_reviewer_reference: str
    clinical_reviewer_reference: str | None
    reviewed_at: datetime
    valid_from: datetime | None
    valid_until: datetime | None
    requires_clinical_review: bool


@dataclass(frozen=True, slots=True)
class FaqImportResult:
    batch_id: UUID
    imported_versions: tuple[UUID, ...]
    published: bool
    source_sha256: str


def parse_datetime(value: str, field: str, row_number: int, errors: list[str]) -> datetime | None:
    if not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"row {row_number}: {field} must be ISO 8601")
        return None
    if parsed.tzinfo is None:
        errors.append(f"row {row_number}: {field} must include a timezone")
        return None
    return parsed.astimezone(UTC)


def parse_boolean(value: str, field: str, row_number: int, errors: list[str]) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    errors.append(f"row {row_number}: {field} must be true or false")
    return False


def parse_faq_csv(content: bytes) -> tuple[FaqImportRow, ...]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FaqImportValidationError(["FAQ CSV must be UTF-8 encoded"]) from exc
    reader = csv.DictReader(io.StringIO(decoded))
    columns = set(reader.fieldnames or [])
    errors: list[str] = []
    missing = REQUIRED_COLUMNS - columns
    unknown = columns - REQUIRED_COLUMNS - OPTIONAL_COLUMNS
    if missing:
        errors.append(f"missing columns: {', '.join(sorted(missing))}")
    if unknown:
        errors.append(f"unknown columns: {', '.join(sorted(unknown))}")
    if errors:
        raise FaqImportValidationError(errors)

    rows: list[FaqImportRow] = []
    seen_versions: set[tuple[str, int]] = set()
    seen_logical_keys: set[str] = set()
    for row_number, raw in enumerate(reader, start=2):
        logical_key = (raw.get("logical_key") or "").strip()
        answer_ro = (raw.get("approved_answer_ro") or "").strip()
        reviewer = (raw.get("administrative_reviewer_reference") or "").strip()
        if not logical_key or len(logical_key) > 160:
            errors.append(f"row {row_number}: logical_key is required and must be at most 160 characters")
        try:
            version_number = int((raw.get("version_number") or "").strip())
            if version_number < 1:
                raise ValueError
        except ValueError:
            errors.append(f"row {row_number}: version_number must be a positive integer")
            version_number = 0
        if not answer_ro:
            errors.append(f"row {row_number}: approved_answer_ro is required")
        if not reviewer:
            errors.append(f"row {row_number}: administrative reviewer is required")
        alternatives = tuple(
            question.strip()
            for question in (raw.get("alternative_questions_ro") or "").split("||")
            if question.strip()
        )
        normalized_alternatives = [normalize_romanian_question(item) for item in alternatives]
        if not alternatives or any(not item for item in normalized_alternatives):
            errors.append(f"row {row_number}: at least one valid alternative question is required")
        if len(set(normalized_alternatives)) != len(normalized_alternatives):
            errors.append(f"row {row_number}: alternative questions contain normalized duplicates")
        requires_clinical = parse_boolean(
            raw.get("requires_clinical_review") or "",
            "requires_clinical_review",
            row_number,
            errors,
        )
        clinical_reviewer = (raw.get("clinical_reviewer_reference") or "").strip() or None
        if requires_clinical and not clinical_reviewer:
            errors.append(f"row {row_number}: clinical reviewer is required")
        reviewed_at = parse_datetime(raw.get("reviewed_at") or "", "reviewed_at", row_number, errors)
        if reviewed_at is None:
            errors.append(f"row {row_number}: reviewed_at is required")
        valid_from = parse_datetime(raw.get("valid_from") or "", "valid_from", row_number, errors)
        valid_until = parse_datetime(raw.get("valid_until") or "", "valid_until", row_number, errors)
        if valid_from and valid_until and valid_until <= valid_from:
            errors.append(f"row {row_number}: valid_until must be after valid_from")
        version_key = (logical_key, version_number)
        if version_key in seen_versions:
            errors.append(f"row {row_number}: duplicate logical_key and version_number")
        seen_versions.add(version_key)
        if logical_key in seen_logical_keys:
            errors.append(f"row {row_number}: each logical_key may appear only once per import")
        seen_logical_keys.add(logical_key)
        if reviewed_at is not None:
            rows.append(
                FaqImportRow(
                    logical_key=logical_key,
                    version_number=version_number,
                    approved_answer_ro=answer_ro,
                    approved_answer_en=(raw.get("approved_answer_en") or "").strip() or None,
                    alternative_questions_ro=alternatives,
                    administrative_reviewer_reference=reviewer,
                    clinical_reviewer_reference=clinical_reviewer,
                    reviewed_at=reviewed_at,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    requires_clinical_review=requires_clinical,
                )
            )
    if not rows:
        errors.append("the import file contains no FAQ rows")
    if errors:
        raise FaqImportValidationError(errors)
    return tuple(rows)


async def import_faq_csv(
    database: AsyncSession,
    *,
    project_id: str,
    source_filename: str,
    content: bytes,
    administrator_account_id: UUID,
    administrator_membership_id: UUID,
    publish: bool,
    embedding_provider: EmbeddingProvider | None = None,
) -> FaqImportResult:
    rows = parse_faq_csv(content)
    source_sha256 = hashlib.sha256(content).hexdigest()
    duplicate = await database.scalar(
        select(FaqImportBatch.id).where(
            FaqImportBatch.project_id == project_id,
            FaqImportBatch.source_sha256 == source_sha256,
            FaqImportBatch.status.in_(("imported", "published")),
        )
    )
    if duplicate is not None:
        raise FaqImportValidationError(["this exact FAQ file was already imported for the project"])
    if embedding_provider is not None and embedding_provider.dimension != 384:
        raise FaqImportValidationError(["the embedding provider must produce 384 dimensions"])

    batch = FaqImportBatch(
        project_id=project_id,
        source_filename=source_filename,
        source_sha256=source_sha256,
        status="validating",
        imported_by_membership_id=administrator_membership_id,
        validation_summary={"row_count": len(rows), "errors": []},
    )
    database.add(batch)
    await database.flush()
    imported: list[tuple[FaqVersion, FaqImportRow]] = []
    for row in rows:
        item = await database.scalar(
            select(FaqItem).where(
                FaqItem.project_id == project_id,
                FaqItem.logical_key == row.logical_key,
            )
        )
        if item is None:
            item = FaqItem(project_id=project_id, logical_key=row.logical_key)
            database.add(item)
            await database.flush()
        existing = await database.scalar(
            select(FaqVersion.id).where(
                FaqVersion.project_id == project_id,
                FaqVersion.faq_item_id == item.id,
                FaqVersion.version_number == row.version_number,
            )
        )
        if existing is not None:
            raise FaqImportValidationError(
                [f"{row.logical_key}@{row.version_number} already exists in this project"]
            )
        version = FaqVersion(
            project_id=project_id,
            faq_item_id=item.id,
            import_batch_id=batch.id,
            version_number=row.version_number,
            approved_answer_ro=row.approved_answer_ro,
            approved_answer_en=row.approved_answer_en,
            publication_status=FaqPublicationStatus.DRAFT,
            valid_from=row.valid_from,
            valid_until=row.valid_until,
            administrative_reviewer_reference=row.administrative_reviewer_reference,
            clinical_reviewer_reference=row.clinical_reviewer_reference,
            reviewed_at=row.reviewed_at,
            requires_clinical_review=row.requires_clinical_review,
        )
        database.add(version)
        await database.flush()
        vectors = (
            embedding_provider.embed(row.alternative_questions_ro)
            if embedding_provider is not None
            else [None] * len(row.alternative_questions_ro)
        )
        if len(vectors) != len(row.alternative_questions_ro):
            raise FaqImportValidationError([f"embedding count mismatch for {row.logical_key}"])
        for question, vector in zip(row.alternative_questions_ro, vectors, strict=True):
            if vector is not None and len(vector) != 384:
                raise FaqImportValidationError([f"invalid embedding dimension for {row.logical_key}"])
            database.add(
                FaqAlternativeQuestion(
                    project_id=project_id,
                    faq_version_id=version.id,
                    question_ro=question,
                    normalized_question=normalize_romanian_question(question),
                    embedding=vector,
                    embedding_model=(embedding_provider.model_name if vector is not None else None),
                    embedded_at=(datetime.now(UTC) if vector is not None else None),
                )
            )
        imported.append((version, row))

    if publish:
        now = datetime.now(UTC)
        for version, row in imported:
            current = await database.scalar(
                select(FaqVersion).where(
                    FaqVersion.project_id == project_id,
                    FaqVersion.faq_item_id == version.faq_item_id,
                    FaqVersion.publication_status == FaqPublicationStatus.PUBLISHED,
                )
            )
            if current is not None:
                current.publication_status = FaqPublicationStatus.RETIRED
                current.retired_at = now
                current.retirement_reason = f"Replaced by version {row.version_number}"
                await record_audit_event(
                    database,
                    project_id=project_id,
                    actor_account_id=administrator_account_id,
                    actor_membership_id=administrator_membership_id,
                    action="faq.version_replaced",
                    outcome="success",
                    target_type="faq_version",
                    target_id=str(current.id),
                    metadata={"replacement_version_id": str(version.id)},
                )
                await database.flush()
            version.publication_status = FaqPublicationStatus.PUBLISHED
            version.published_by_membership_id = administrator_membership_id
            version.published_at = now
            await record_audit_event(
                database,
                project_id=project_id,
                actor_account_id=administrator_account_id,
                actor_membership_id=administrator_membership_id,
                action="faq.version_published",
                outcome="success",
                target_type="faq_version",
                target_id=str(version.id),
                metadata={"logical_key": row.logical_key, "version_number": row.version_number},
            )
        batch.status = "published"
    else:
        batch.status = "imported"
    batch.validation_summary = {
        "row_count": len(rows),
        "errors": [],
        "embeddings_generated": embedding_provider is not None,
        "embedding_model": embedding_provider.model_name if embedding_provider else None,
    }
    await record_audit_event(
        database,
        project_id=project_id,
        actor_account_id=administrator_account_id,
        actor_membership_id=administrator_membership_id,
        action="faq.import_completed",
        outcome="success",
        target_type="faq_import_batch",
        target_id=str(batch.id),
        metadata={"row_count": len(rows), "published": publish},
    )
    await database.flush()
    return FaqImportResult(
        batch_id=batch.id,
        imported_versions=tuple(version.id for version, _row in imported),
        published=publish,
        source_sha256=source_sha256,
    )


async def retire_published_faq(
    database: AsyncSession,
    *,
    project_id: str,
    logical_key: str,
    reason: str,
    administrator_account_id: UUID,
    administrator_membership_id: UUID,
) -> UUID:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise FaqImportValidationError(["an emergency-withdrawal reason is required"])
    version = await database.scalar(
        select(FaqVersion)
        .join(
            FaqItem,
            (FaqItem.project_id == FaqVersion.project_id)
            & (FaqItem.id == FaqVersion.faq_item_id),
        )
        .where(
            FaqVersion.project_id == project_id,
            FaqItem.logical_key == logical_key,
            FaqVersion.publication_status == FaqPublicationStatus.PUBLISHED,
        )
        .with_for_update()
    )
    if version is None:
        raise FaqImportValidationError(["no published FAQ exists for this logical key"])
    version.publication_status = FaqPublicationStatus.RETIRED
    version.retired_at = datetime.now(UTC)
    version.retirement_reason = normalized_reason
    await record_audit_event(
        database,
        project_id=project_id,
        actor_account_id=administrator_account_id,
        actor_membership_id=administrator_membership_id,
        action="faq.emergency_withdrawal",
        outcome="success",
        target_type="faq_version",
        target_id=str(version.id),
        metadata={"logical_key": logical_key, "reason": normalized_reason},
    )
    return version.id


async def expire_due_faq_versions(
    database: AsyncSession,
    *,
    project_id: str,
    now: datetime | None = None,
) -> tuple[UUID, ...]:
    current_time = now or datetime.now(UTC)
    versions = list(
        await database.scalars(
            select(FaqVersion)
            .where(
                FaqVersion.project_id == project_id,
                FaqVersion.publication_status == FaqPublicationStatus.PUBLISHED,
                FaqVersion.valid_until.is_not(None),
                FaqVersion.valid_until < current_time,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for version in versions:
        version.publication_status = FaqPublicationStatus.EXPIRED
        await record_audit_event(
            database,
            project_id=project_id,
            action="faq.version_expired",
            outcome="success",
            target_type="faq_version",
            target_id=str(version.id),
            metadata={"valid_until": version.valid_until.isoformat()},
        )
    return tuple(version.id for version in versions)
