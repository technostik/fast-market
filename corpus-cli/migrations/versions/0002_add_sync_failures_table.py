"""add sync_failures table

Revision ID: 0002_add_sync_failures_table
Revises: 0001_initial_schema
Create Date: 2026-03-17
"""

from __future__ import annotations

from alembic import op

revision = "0002_add_sync_failures_table"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_failures (
            id INTEGER PRIMARY KEY,
            source_plugin TEXT NOT NULL,
            source_id TEXT NOT NULL,
            error_message TEXT NOT NULL,
            error_type TEXT NOT NULL,
            failed_at TEXT NOT NULL,
            retry_count INTEGER DEFAULT 0,
            last_retry_at TEXT,
            UNIQUE(source_plugin, source_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sync_failures_source_plugin ON sync_failures(source_plugin)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sync_failures_error_type ON sync_failures(error_type)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sync_failures_error_type")
    op.execute("DROP INDEX IF EXISTS ix_sync_failures_source_plugin")
    op.execute("DROP TABLE IF EXISTS sync_failures")
