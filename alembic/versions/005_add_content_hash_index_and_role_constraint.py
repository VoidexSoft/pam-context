"""Add index on documents.content_hash and CHECK constraint on user_project_roles.role.

Revision ID: 005
Revises: 004
Create Date: 2026-02-16 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. CHECK constraint runs inside the transaction (fast, safe)
    op.create_check_constraint(
        "ck_user_project_roles_role",
        "user_project_roles",
        "role IN ('viewer', 'editor', 'admin')",
    )

    # 2. CONCURRENT index must run outside a transaction
    # autocommit_block() commits the preceding CHECK constraint transaction,
    # then switches to autocommit mode for CREATE INDEX CONCURRENTLY.
    with op.get_context().autocommit_block():
        op.create_index(
            "idx_documents_content_hash",
            "documents",
            ["content_hash"],
            if_not_exists=True,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    # Drop index first (needs autocommit for CONCURRENTLY)
    with op.get_context().autocommit_block():
        op.drop_index(
            "idx_documents_content_hash",
            table_name="documents",
            postgresql_concurrently=True,
            if_exists=True,
        )

    # Then drop the CHECK constraint (transactional)
    op.drop_constraint("ck_user_project_roles_role", "user_project_roles")
