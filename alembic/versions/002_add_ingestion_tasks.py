"""Add ingestion_tasks table for background task tracking.

Revision ID: 002
Revises: 001
Create Date: 2026-02-11 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("folder_path", sa.Text, nullable=False),
        sa.Column("total_documents", sa.Integer, server_default="0"),
        sa.Column("processed_documents", sa.Integer, server_default="0"),
        sa.Column("succeeded", sa.Integer, server_default="0"),
        sa.Column("skipped", sa.Integer, server_default="0"),
        sa.Column("failed", sa.Integer, server_default="0"),
        sa.Column("results", JSONB, server_default="[]"),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    op.create_index("idx_ingestion_tasks_status", "ingestion_tasks", ["status"])
    op.create_index("idx_ingestion_tasks_created_at", "ingestion_tasks", ["created_at"])


def downgrade() -> None:
    op.drop_table("ingestion_tasks")
