"""Create the initial project-isolated platform schema.

Revision ID: 0001_project_isolated_schema
Revises:
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_project_isolated_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


operator_role = postgresql.ENUM(
    "operator", "administrator", name="operator_role", create_type=False
)
conversation_state = postgresql.ENUM(
    "BOT",
    "WAITING_HUMAN",
    "HUMAN_ACTIVE",
    "WAITING_USER",
    "CLOSED",
    name="conversation_state",
    create_type=False,
)
ticket_status = postgresql.ENUM(
    "NEW",
    "CLAIMED",
    "WAITING_USER",
    "RESOLVED",
    "CLOSED",
    name="ticket_status",
    create_type=False,
)
message_direction = postgresql.ENUM(
    "inbound", "outbound", name="message_direction", create_type=False
)
message_sender_type = postgresql.ENUM(
    "user", "bot", "operator", "system", name="message_sender_type", create_type=False
)
message_type = postgresql.ENUM(
    "text", "interactive", "unsupported", "system", name="message_type", create_type=False
)
delivery_status = postgresql.ENUM(
    "received",
    "queued",
    "sent",
    "delivered",
    "read",
    "failed",
    name="delivery_status",
    create_type=False,
)
faq_publication_status = postgresql.ENUM(
    "draft",
    "published",
    "retired",
    "expired",
    name="faq_publication_status",
    create_type=False,
)
template_status = postgresql.ENUM(
    "draft",
    "submitted",
    "approved",
    "rejected",
    "paused",
    name="template_status",
    create_type=False,
)
outbox_status = postgresql.ENUM(
    "pending", "processing", "sent", "failed", name="outbox_status", create_type=False
)
notification_type = postgresql.ENUM(
    "user_replied",
    "ticket_reopened",
    "ticket_assigned",
    name="notification_type",
    create_type=False,
)

ENUMS = (
    operator_role,
    conversation_state,
    ticket_status,
    message_direction,
    message_sender_type,
    message_type,
    delivery_status,
    faq_publication_status,
    template_status,
    outbox_status,
    notification_type,
)


def uuid_primary_key() -> sa.Column:
    return sa.Column(
        "id",
        sa.Uuid(),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def timestamp_columns() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def project_id_column(*, nullable: bool = False) -> sa.Column:
    return sa.Column("project_id", sa.String(length=32), nullable=nullable)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    bind = op.get_bind()
    for enum in ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("public_name", sa.String(length=160), nullable=False),
        sa.Column(
            "content_status",
            sa.String(length=40),
            server_default="development_placeholder",
            nullable=False,
        ),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )

    op.create_table(
        "operator_accounts",
        uuid_primary_key(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("failed_login_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lockout_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_operator_accounts"),
        sa.UniqueConstraint("email", name="uq_operator_accounts_email"),
    )

    op.create_table(
        "operator_project_memberships",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("operator_account_id", sa.Uuid(), nullable=False),
        sa.Column("role", operator_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["operator_account_id"],
            ["operator_accounts.id"],
            name=op.f("fk_operator_project_memberships_operator_account_id_operator_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_operator_project_memberships_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_operator_project_memberships"),
        sa.UniqueConstraint(
            "project_id", "id", name="uq_operator_project_memberships_project_id_id"
        ),
        sa.UniqueConstraint(
            "project_id",
            "operator_account_id",
            name="uq_operator_project_memberships_project_id_operator_account_id",
        ),
    )
    op.create_index(
        "ix_operator_project_memberships_operator_account_id",
        "operator_project_memberships",
        ["operator_account_id"],
    )
    op.create_index(
        "ix_operator_project_memberships_project_id",
        "operator_project_memberships",
        ["project_id"],
    )

    op.create_table(
        "operator_sessions",
        uuid_primary_key(),
        sa.Column("operator_account_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("csrf_secret_hash", sa.String(length=128), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=160), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["operator_account_id"],
            ["operator_accounts.id"],
            name="fk_operator_sessions_operator_account_id_operator_accounts",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_operator_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_operator_sessions_token_hash"),
    )
    op.create_index(
        "ix_operator_sessions_operator_account_id", "operator_sessions", ["operator_account_id"]
    )

    op.create_table(
        "password_reset_credentials",
        uuid_primary_key(),
        sa.Column("operator_account_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=True),
        project_id_column(nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["operator_account_id"],
            ["operator_accounts.id"],
            name=op.f("fk_password_reset_credentials_operator_account_id_operator_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "created_by_membership_id"],
            [
                "operator_project_memberships.project_id",
                "operator_project_memberships.id",
            ],
            name=op.f("fk_password_reset_credentials_project_id_created_by_membership_id_operator_project_memberships"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_credentials"),
        sa.UniqueConstraint(
            "token_hash", name="uq_password_reset_credentials_token_hash"
        ),
    )
    op.create_index(
        "ix_password_reset_credentials_operator_account_id",
        "password_reset_credentials",
        ["operator_account_id"],
    )

    op.create_table(
        "retention_policies",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("message_content_days", sa.Integer(), nullable=False),
        sa.Column("tickets_and_notes_days", sa.Integer(), nullable=False),
        sa.Column("audit_events_days", sa.Integer(), nullable=False),
        sa.Column("application_logs_days", sa.Integer(), nullable=False),
        sa.Column("backups_days", sa.Integer(), nullable=False),
        sa.Column("privacy_warning_inactivity_days", sa.Integer(), nullable=False),
        sa.Column("resolved_ticket_reopen_days", sa.Integer(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("version > 0", name="ck_retention_policies_positive_version"),
        sa.CheckConstraint(
            "message_content_days > 0",
            name="ck_retention_policies_positive_message_content_days",
        ),
        sa.CheckConstraint(
            "tickets_and_notes_days > 0",
            name="ck_retention_policies_positive_tickets_notes_days",
        ),
        sa.CheckConstraint(
            "audit_events_days > 0", name="ck_retention_policies_positive_audit_days"
        ),
        sa.CheckConstraint(
            "application_logs_days > 0", name="ck_retention_policies_positive_log_days"
        ),
        sa.CheckConstraint("backups_days > 0", name="ck_retention_policies_positive_backup_days"),
        sa.CheckConstraint(
            "privacy_warning_inactivity_days > 0",
            name="ck_retention_policies_positive_privacy_warning_inactivity_days",
        ),
        sa.CheckConstraint(
            "resolved_ticket_reopen_days >= 0",
            name="ck_retention_policies_valid_reopen_days",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_retention_policies_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retention_policies"),
        sa.UniqueConstraint("project_id", "id", name="uq_retention_policies_project_id_id"),
        sa.UniqueConstraint(
            "project_id", "version", name="uq_retention_policies_project_id_version"
        ),
    )
    op.create_index("ix_retention_policies_project_id", "retention_policies", ["project_id"])
    op.create_index(
        "uq_retention_policies_one_current_per_project",
        "retention_policies",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "project_whatsapp_configurations",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("phone_number_id", sa.String(length=128), nullable=True),
        sa.Column("waba_id", sa.String(length=128), nullable=True),
        sa.Column("meta_app_id", sa.String(length=128), nullable=True),
        sa.Column("credential_binding", sa.String(length=160), nullable=True),
        sa.Column("webhook_binding", sa.String(length=160), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_whatsapp_configurations_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_project_whatsapp_configurations"),
        sa.UniqueConstraint(
            "phone_number_id", name="uq_project_whatsapp_configurations_phone_number_id"
        ),
        sa.UniqueConstraint(
            "project_id", name="uq_project_whatsapp_configurations_project_id"
        ),
        sa.UniqueConstraint(
            "project_id", "id", name="uq_project_whatsapp_configurations_project_id_id"
        ),
    )
    op.create_index(
        "ix_project_whatsapp_configurations_project_id",
        "project_whatsapp_configurations",
        ["project_id"],
    )

    op.create_table(
        "whatsapp_templates",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("template_name", sa.String(length=512), nullable=False),
        sa.Column("language_code", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=160), nullable=False),
        sa.Column("status", template_status, nullable=False),
        sa.Column("meta_template_id", sa.String(length=128), nullable=True),
        sa.Column("approved_body_snapshot", sa.Text(), nullable=True),
        sa.Column("variables_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_whatsapp_templates_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_whatsapp_templates"),
        sa.UniqueConstraint("project_id", "id", name="uq_whatsapp_templates_project_id_id"),
        sa.UniqueConstraint(
            "project_id",
            "template_name",
            "language_code",
            name="uq_whatsapp_templates_project_id_template_name_language_code",
        ),
    )
    op.create_index("ix_whatsapp_templates_project_id", "whatsapp_templates", ["project_id"])

    op.create_table(
        "conversations",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("whatsapp_user_id", sa.String(length=128), nullable=False),
        sa.Column("phone_number_e164", sa.String(length=32), nullable=True),
        sa.Column("state", conversation_state, server_default="BOT", nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("privacy_warning_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unsupported_warning_sent_at", sa.DateTime(timezone=True), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_conversations_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.UniqueConstraint("project_id", "id", name="uq_conversations_project_id_id"),
        sa.UniqueConstraint(
            "project_id", "whatsapp_user_id", name="uq_conversations_project_id_whatsapp_user_id"
        ),
    )
    op.create_index("ix_conversations_project_id", "conversations", ["project_id"])

    op.create_table(
        "tickets",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("status", ticket_status, server_default="NEW", nullable=False),
        sa.Column("assigned_membership_id", sa.Uuid(), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("waiting_user_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopen_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id", "assigned_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            name=op.f("fk_tickets_project_id_assigned_membership_id_operator_project_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_tickets_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "conversation_id"],
            ["conversations.project_id", "conversations.id"],
            name="fk_tickets_project_id_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tickets"),
        sa.UniqueConstraint("project_id", "id", name="uq_tickets_project_id_id"),
        sa.UniqueConstraint("project_id", "reference", name="uq_tickets_project_id_reference"),
    )
    op.create_index("ix_tickets_assigned_membership_id", "tickets", ["assigned_membership_id"])
    op.create_index("ix_tickets_conversation_id", "tickets", ["conversation_id"])
    op.create_index("ix_tickets_project_id", "tickets", ["project_id"])
    op.create_index(
        "uq_tickets_one_active_per_conversation",
        "tickets",
        ["project_id", "conversation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('NEW', 'CLAIMED', 'WAITING_USER')"),
    )

    op.create_table(
        "whatsapp_messages",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("operator_membership_id", sa.Uuid(), nullable=True),
        sa.Column("meta_message_id", sa.String(length=256), nullable=True),
        sa.Column("client_reference", sa.String(length=128), nullable=True),
        sa.Column("direction", message_direction, nullable=False),
        sa.Column("sender_type", message_sender_type, nullable=False),
        sa.Column("message_type", message_type, nullable=False),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("attachment_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("delivery_status", delivery_status, nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_summary", sa.String(length=512), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id", "conversation_id"],
            ["conversations.project_id", "conversations.id"],
            name="fk_whatsapp_messages_project_id_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_whatsapp_messages_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "operator_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            name=op.f("fk_whatsapp_messages_project_id_operator_membership_id_operator_project_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_whatsapp_messages_project_id_ticket_id_tickets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_whatsapp_messages"),
        sa.UniqueConstraint("project_id", "id", name="uq_whatsapp_messages_project_id_id"),
        sa.UniqueConstraint(
            "project_id", "meta_message_id", name="uq_whatsapp_messages_project_id_meta_message_id"
        ),
    )
    op.create_index("ix_whatsapp_messages_conversation_id", "whatsapp_messages", ["conversation_id"])
    op.create_index("ix_whatsapp_messages_operator_membership_id", "whatsapp_messages", ["operator_membership_id"])
    op.create_index("ix_whatsapp_messages_project_id", "whatsapp_messages", ["project_id"])
    op.create_index("ix_whatsapp_messages_ticket_id", "whatsapp_messages", ["ticket_id"])

    op.create_table(
        "internal_notes",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("author_membership_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id", "author_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            name=op.f("fk_internal_notes_project_id_author_membership_id_operator_project_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_internal_notes_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_internal_notes_project_id_ticket_id_tickets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_internal_notes"),
        sa.UniqueConstraint("project_id", "id", name="uq_internal_notes_project_id_id"),
    )
    op.create_index("ix_internal_notes_author_membership_id", "internal_notes", ["author_membership_id"])
    op.create_index("ix_internal_notes_project_id", "internal_notes", ["project_id"])
    op.create_index("ix_internal_notes_ticket_id", "internal_notes", ["ticket_id"])

    op.create_table(
        "operator_notifications",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_membership_id", sa.Uuid(), nullable=False),
        sa.Column("notification_type", notification_type, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id", "recipient_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            name=op.f("fk_operator_notifications_project_id_recipient_membership_id_operator_project_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_operator_notifications_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            name="fk_operator_notifications_project_id_ticket_id_tickets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_operator_notifications"),
        sa.UniqueConstraint("project_id", "id", name="uq_operator_notifications_project_id_id"),
    )
    op.create_index("ix_operator_notifications_project_id", "operator_notifications", ["project_id"])
    op.create_index("ix_operator_notifications_recipient_membership_id", "operator_notifications", ["recipient_membership_id"])
    op.create_index("ix_operator_notifications_ticket_id", "operator_notifications", ["ticket_id"])

    op.create_table(
        "faq_items",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("logical_key", sa.String(length=160), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_faq_items_project_id_projects", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_faq_items"),
        sa.UniqueConstraint("project_id", "id", name="uq_faq_items_project_id_id"),
        sa.UniqueConstraint("project_id", "logical_key", name="uq_faq_items_project_id_logical_key"),
    )
    op.create_index("ix_faq_items_project_id", "faq_items", ["project_id"])

    op.create_table(
        "faq_import_batches",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("imported_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("validation_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id", "imported_by_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            name=op.f("fk_faq_import_batches_project_id_imported_by_membership_id_operator_project_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_faq_import_batches_project_id_projects", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_faq_import_batches"),
        sa.UniqueConstraint("project_id", "id", name="uq_faq_import_batches_project_id_id"),
    )
    op.create_index("ix_faq_import_batches_project_id", "faq_import_batches", ["project_id"])

    op.create_table(
        "faq_versions",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("faq_item_id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("approved_answer_ro", sa.Text(), nullable=False),
        sa.Column("approved_answer_en", sa.Text(), nullable=True),
        sa.Column("publication_status", faq_publication_status, server_default="draft", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("administrative_reviewer_reference", sa.String(length=320), nullable=True),
        sa.Column("clinical_reviewer_reference", sa.String(length=320), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_membership_id", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retirement_reason", sa.String(length=512), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id", "faq_item_id"],
            ["faq_items.project_id", "faq_items.id"],
            name="fk_faq_versions_project_id_faq_item_id_faq_items",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_faq_versions_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "import_batch_id"],
            ["faq_import_batches.project_id", "faq_import_batches.id"],
            name="fk_faq_versions_project_id_import_batch_id_faq_import_batches",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "published_by_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            name=op.f("fk_faq_versions_project_id_published_by_membership_id_operator_project_memberships"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_faq_versions"),
        sa.UniqueConstraint("project_id", "id", name="uq_faq_versions_project_id_id"),
        sa.UniqueConstraint(
            "project_id", "faq_item_id", "version_number", name="uq_faq_versions_project_id_faq_item_id_version_number"
        ),
    )
    op.create_index("ix_faq_versions_faq_item_id", "faq_versions", ["faq_item_id"])
    op.create_index("ix_faq_versions_import_batch_id", "faq_versions", ["import_batch_id"])
    op.create_index("ix_faq_versions_project_id", "faq_versions", ["project_id"])
    op.create_index("ix_faq_versions_published_by_membership_id", "faq_versions", ["published_by_membership_id"])
    op.create_index(
        "uq_faq_versions_one_published_per_item",
        "faq_versions",
        ["project_id", "faq_item_id"],
        unique=True,
        postgresql_where=sa.text("publication_status = 'published'"),
    )

    op.create_table(
        "faq_alternative_questions",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("faq_version_id", sa.Uuid(), nullable=False),
        sa.Column("question_ro", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dim=384), nullable=True),
        sa.Column("embedding_model", sa.String(length=256), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id", "faq_version_id"],
            ["faq_versions.project_id", "faq_versions.id"],
            name=op.f("fk_faq_alternative_questions_project_id_faq_version_id_faq_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_faq_alternative_questions_project_id_projects", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_faq_alternative_questions"),
        sa.UniqueConstraint("project_id", "id", name="uq_faq_alternative_questions_project_id_id"),
        sa.UniqueConstraint(
            "project_id",
            "faq_version_id",
            "normalized_question",
            name=op.f("uq_faq_alternative_questions_project_id_faq_version_id_normalized_question"),
        ),
    )
    op.create_index("ix_faq_alternative_questions_faq_version_id", "faq_alternative_questions", ["faq_version_id"])
    op.create_index("ix_faq_alternative_questions_project_id", "faq_alternative_questions", ["project_id"])

    op.create_table(
        "outbox_entries",
        uuid_primary_key(),
        project_id_column(),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", outbox_status, server_default="pending", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(length=160), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_error_code", sa.String(length=128), nullable=True),
        sa.Column("terminal_error_summary", sa.String(length=512), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["project_id", "message_id"],
            ["whatsapp_messages.project_id", "whatsapp_messages.id"],
            name="fk_outbox_entries_project_id_message_id_whatsapp_messages",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_outbox_entries_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "template_id"],
            ["whatsapp_templates.project_id", "whatsapp_templates.id"],
            name="fk_outbox_entries_project_id_template_id_whatsapp_templates",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_entries"),
        sa.UniqueConstraint("project_id", "id", name="uq_outbox_entries_project_id_id"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_outbox_entries_project_id_idempotency_key"),
    )
    op.create_index("ix_outbox_entries_message_id", "outbox_entries", ["message_id"])
    op.create_index("ix_outbox_entries_project_id", "outbox_entries", ["project_id"])
    op.create_index("ix_outbox_entries_template_id", "outbox_entries", ["template_id"])
    op.create_index(
        "ix_outbox_entries_claimable",
        "outbox_entries",
        ["status", "available_at"],
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )

    op.create_table(
        "audit_events",
        uuid_primary_key(),
        project_id_column(nullable=True),
        sa.Column("actor_account_id", sa.Uuid(), nullable=True),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=160), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=True),
        sa.Column("target_id", sa.String(length=160), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["operator_accounts.id"],
            name="fk_audit_events_actor_account_id_operator_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "actor_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            name=op.f("fk_audit_events_project_id_actor_membership_id_operator_project_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_audit_events_project_id_projects", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.UniqueConstraint("project_id", "id", name="uq_audit_events_project_id_id"),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_actor_account_id", "audit_events", ["actor_account_id"])
    op.create_index("ix_audit_events_actor_membership_id", "audit_events", ["actor_membership_id"])
    op.create_index("ix_audit_events_project_id", "audit_events", ["project_id"])


def downgrade() -> None:
    for table_name in (
        "audit_events",
        "outbox_entries",
        "faq_alternative_questions",
        "faq_versions",
        "faq_import_batches",
        "faq_items",
        "operator_notifications",
        "internal_notes",
        "whatsapp_messages",
        "tickets",
        "conversations",
        "whatsapp_templates",
        "project_whatsapp_configurations",
        "retention_policies",
        "password_reset_credentials",
        "operator_sessions",
        "operator_project_memberships",
        "operator_accounts",
        "projects",
    ):
        op.drop_table(table_name)

    bind = op.get_bind()
    for enum in reversed(ENUMS):
        enum.drop(bind, checkfirst=True)
