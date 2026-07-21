from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import FaqPublicationStatus, database_enum
from app.db.models.mixins import ProjectOwnedMixin, TimestampMixin, UuidPrimaryKeyMixin


class FaqItem(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "faq_items"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "logical_key"),
    )

    logical_key: Mapped[str] = mapped_column(String(160), nullable=False)


class FaqImportBatch(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "faq_import_batches"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        ForeignKeyConstraint(
            ["project_id", "imported_by_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            ondelete="RESTRICT",
        ),
    )

    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    imported_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    validation_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class FaqVersion(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "faq_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "faq_item_id", "version_number"),
        ForeignKeyConstraint(
            ["project_id", "faq_item_id"],
            ["faq_items.project_id", "faq_items.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "import_batch_id"],
            ["faq_import_batches.project_id", "faq_import_batches.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "published_by_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            ondelete="RESTRICT",
        ),
        Index(
            "uq_faq_versions_one_published_per_item",
            "project_id",
            "faq_item_id",
            unique=True,
            postgresql_where=text("publication_status = 'published'"),
        ),
    )

    faq_item_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    import_batch_id: Mapped[UUID | None] = mapped_column(index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_answer_ro: Mapped[str] = mapped_column(Text, nullable=False)
    approved_answer_en: Mapped[str | None] = mapped_column(Text)
    publication_status: Mapped[FaqPublicationStatus] = mapped_column(
        database_enum(FaqPublicationStatus, "faq_publication_status"),
        nullable=False,
        server_default=FaqPublicationStatus.DRAFT.value,
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    administrative_reviewer_reference: Mapped[str | None] = mapped_column(String(320))
    clinical_reviewer_reference: Mapped[str | None] = mapped_column(String(320))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_membership_id: Mapped[UUID | None] = mapped_column(index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retirement_reason: Mapped[str | None] = mapped_column(String(512))
    requires_clinical_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class FaqAlternativeQuestion(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "faq_alternative_questions"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "faq_version_id", "normalized_question"),
        ForeignKeyConstraint(
            ["project_id", "faq_version_id"],
            ["faq_versions.project_id", "faq_versions.id"],
            ondelete="RESTRICT",
        ),
    )

    faq_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    question_ro: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    embedding_model: Mapped[str | None] = mapped_column(String(256))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
