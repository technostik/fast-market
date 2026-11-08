"""add profile column to documents and pool_items

Revision ID: 0006_add_profile_column
Revises: 0005_add_field_definitions_table
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_add_profile_column"
down_revision = "0005_add_field_definitions_table"
branch_labels = None
depends_on = None

# Every corpus row predating multi-profile support belongs to the joriel
# persona: the corpus only ever ran under the active joriel profile before the
# profile column existed.
_LEGACY_PROFILE = "joriel"


def upgrade() -> None:
    # Additive DDL: both columns are nullable so the ALTER works on existing
    # SQLite files. They are backfilled right after, then always written by the
    # corpus code paths (upsert_document / upsert_pool_item).
    op.add_column("documents", sa.Column("profile", sa.String(), nullable=True))
    op.add_column("pool_items", sa.Column("profile", sa.String(), nullable=True))
    op.execute(
        f"UPDATE documents SET profile = '{_LEGACY_PROFILE}' "
        "WHERE profile IS NULL OR profile = ''"
    )
    op.execute(
        f"UPDATE pool_items SET profile = '{_LEGACY_PROFILE}' "
        "WHERE profile IS NULL OR profile = ''"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_profile ON documents(profile)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pool_items_profile ON pool_items(profile)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_profile")
    op.execute("DROP INDEX IF EXISTS ix_pool_items_profile")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("profile")
    with op.batch_alter_table("pool_items") as batch:
        batch.drop_column("profile")
