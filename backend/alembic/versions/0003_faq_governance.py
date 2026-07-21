"""Add explicit clinical-review governance state to FAQ versions.

Revision ID: 0003_faq_governance
Revises: 0002_authentication_security
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_faq_governance"
down_revision: str | None = "0002_authentication_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "faq_versions",
        sa.Column(
            "requires_clinical_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("faq_versions", "requires_clinical_review")
