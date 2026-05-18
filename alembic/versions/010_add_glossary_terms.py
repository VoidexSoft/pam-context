"""Add glossary_terms table for semantic metadata layer.

Revision ID: 010
Revises: 009
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "glossary_terms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("canonical", sa.String(300), nullable=False),
        sa.Column("aliases", ARRAY(sa.Text), server_default=sa.text("'{}'::text[]")),
        sa.Column("definition", sa.Text, nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "category IN ('metric', 'team', 'product', 'acronym', 'concept', 'other')",
            name="ck_glossary_terms_category",
        ),
        sa.UniqueConstraint("project_id", "canonical", name="uq_glossary_terms_project_canonical"),
        comment="Curated domain terminology with aliases for query expansion",
    )
    op.create_index("ix_glossary_terms_project_id", "glossary_terms", ["project_id"])
    op.create_index("ix_glossary_terms_category", "glossary_terms", ["category"])
    op.create_index("ix_glossary_terms_canonical", "glossary_terms", ["canonical"])


def downgrade() -> None:
    op.drop_index("ix_glossary_terms_canonical", table_name="glossary_terms")
    op.drop_index("ix_glossary_terms_category", table_name="glossary_terms")
    op.drop_index("ix_glossary_terms_project_id", table_name="glossary_terms")
    op.drop_table("glossary_terms")
