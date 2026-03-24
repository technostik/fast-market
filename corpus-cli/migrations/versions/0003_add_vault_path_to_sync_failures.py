"""add vault_path to sync_failures

Revision ID: 0003_add_vault_path_to_sync_failures
Revises: 0002_add_sync_failures_table
Create Date: 2026-03-18
"""

from __future__ import annotations

from alembic import op

revision = "0003_add_vault_path_to_sync_failures"
down_revision = "0002_add_sync_failures_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sync_failures ADD COLUMN vault_path TEXT")


def downgrade() -> None:
    op.execute("DROP COLUMN vault_path")
