from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class UuidPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProjectOwnedMixin:
    @declared_attr
    def project_id(cls) -> Mapped[str]:
        return mapped_column(
            String(32),
            ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )

