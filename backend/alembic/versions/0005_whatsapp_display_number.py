"""Store the configured WhatsApp display phone number.

Revision ID: 0005_whatsapp_display_number
Revises: 0004_meta_whatsapp
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_whatsapp_display_number"
down_revision: str | None = "0004_meta_whatsapp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_whatsapp_configurations",
        sa.Column("display_phone_number", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_whatsapp_configurations", "display_phone_number")
