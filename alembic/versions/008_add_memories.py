"""Add memories table for discrete fact storage with importance scoring.

Revision ID: 008
Revises: 007
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), index=True),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source", sa.String(100)),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("importance", sa.Float, server_default=sa.text("0.5")),
        sa.Column("access_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "type IN ('fact', 'preference', 'observation', 'conversation_summary')",
            name="ck_memories_type",
        ),
        sa.CheckConstraint("importance >= 0 AND importance <= 1", name="ck_memories_importance"),
        comment="Discrete memories (facts, preferences, observations) with importance scoring",
    )
    # Composite index for user-scoped queries
    op.create_index("ix_memories_user_project", "memories", ["user_id", "project_id"])
    # Index for TTL expiration cleanup
    op.create_index("ix_memories_expires_at", "memories", ["expires_at"], postgresql_where=sa.text("expires_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_memories_expires_at", table_name="memories")
    op.drop_index("ix_memories_user_project", table_name="memories")
    op.drop_table("memories")
