"""add pool_items table

Revision ID: 0004_add_pool_items_table
Revises: 0003_add_vault_path_to_sync_failures
Create Date: 2026-05-29
"""

from __future__ import annotations

from alembic import op

revision = "0004_add_pool_items_table"
down_revision = "0003_add_vault_path_to_sync_failures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pool_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_plugin TEXT NOT NULL,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            added_at TEXT NOT NULL,
            synced_at TEXT,
            UNIQUE(source_plugin, source_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pool_items_source_plugin ON pool_items(source_plugin)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pool_items_status ON pool_items(status)"
    )
    # Pre-populate YouTube items from existing documents as already-synced so
    # scan discovery skips them and sync doesn't re-fetch them.
    op.execute(
        """
        INSERT OR IGNORE INTO pool_items
            (source_plugin, source_id, status, metadata_json, added_at, synced_at)
        SELECT
            source_plugin,
            source_id,
            'synced',
            COALESCE(metadata_json, '{}'),
            COALESCE(updated_at, datetime('now')),
            COALESCE(updated_at, datetime('now'))
        FROM documents
        WHERE source_plugin = 'youtube'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pool_items_status")
    op.execute("DROP INDEX IF EXISTS ix_pool_items_source_plugin")
    op.execute("DROP TABLE IF EXISTS pool_items")
