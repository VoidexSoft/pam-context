"""Add extracted_entities table for structured entity extraction.

Revision ID: 004
Revises: 003
Create Date: 2026-02-11 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extracted_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_data", JSONB, nullable=False),
        sa.Column("confidence", sa.Float, server_default=sa.text("0.0")),
        sa.Column(
            "source_segment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("segments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_text", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        comment="Structured entities extracted from document segments",
    )
    op.create_index("ix_extracted_entities_type", "extracted_entities", ["entity_type"])
    op.create_index("ix_extracted_entities_segment", "extracted_entities", ["source_segment_id"])


def downgrade() -> None:
    op.drop_table("extracted_entities")
