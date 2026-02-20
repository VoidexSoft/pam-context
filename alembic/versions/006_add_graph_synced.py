"""Add graph_synced and graph_sync_retries columns to documents table.

Revision ID: 006
Revises: 005
Create Date: 2026-02-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("graph_synced", sa.Boolean, server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "documents",
        sa.Column("graph_sync_retries", sa.Integer, server_default=sa.text("0"), nullable=False),
    )
    op.create_index("ix_documents_graph_synced", "documents", ["graph_synced"])


def downgrade() -> None:
    op.drop_index("ix_documents_graph_synced", table_name="documents")
    op.drop_column("documents", "graph_sync_retries")
    op.drop_column("documents", "graph_synced")
