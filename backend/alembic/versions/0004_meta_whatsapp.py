"""Add the Meta WhatsApp webhook ledger and template message type.

Revision ID: 0004_meta_whatsapp
Revises: 0003_faq_governance
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_meta_whatsapp"
down_revision: str | None = "0003_faq_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE message_type ADD VALUE IF NOT EXISTS 'template'")
    op.create_table(
        "whatsapp_webhook_events",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event_key", sa.String(length=512), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("phone_number_id", sa.String(length=128), nullable=False),
        sa.Column("provider_message_id", sa.String(length=256), nullable=True),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_whatsapp_webhook_events_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_whatsapp_webhook_events"),
        sa.UniqueConstraint(
            "project_id",
            "event_key",
            name="uq_whatsapp_webhook_events_project_id_event_key",
        ),
        sa.UniqueConstraint(
            "project_id",
            "id",
            name="uq_whatsapp_webhook_events_project_id_id",
        ),
    )
    op.create_index(
        "ix_whatsapp_webhook_events_project_id",
        "whatsapp_webhook_events",
        ["project_id"],
    )
    op.create_index(
        "ix_whatsapp_webhook_events_provider_message_id",
        "whatsapp_webhook_events",
        ["provider_message_id"],
    )


def downgrade() -> None:
    op.drop_table("whatsapp_webhook_events")
    # PostgreSQL enum values are intentionally retained; removing a value safely
    # requires rebuilding every dependent column and is not needed for rollback.
