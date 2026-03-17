"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-17
"""

from __future__ import annotations

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            handle TEXT NOT NULL,
            source_plugin TEXT NOT NULL,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            url TEXT,
            updated_at TEXT,
            duration_seconds INTEGER,
            privacy_status TEXT,
            content_hash TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            UNIQUE(source_plugin, source_id),
            UNIQUE(handle)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            source_plugin TEXT NOT NULL,
            source_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            UNIQUE(source_plugin, source_id, chunk_index)
        )
        """
    )
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            source_plugin, source_id, content
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_source_plugin ON documents(source_plugin)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_updated_at ON documents(updated_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_privacy_status ON documents(privacy_status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_source_plugin_source_id ON chunks(source_plugin, source_id)")

    bind = op.get_bind()
    cols = [row[1] for row in bind.exec_driver_sql("PRAGMA table_info(documents)").fetchall()]
    if "privacy_status" not in cols:
        op.execute("ALTER TABLE documents ADD COLUMN privacy_status TEXT")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chunks_fts")
    op.execute("DROP INDEX IF EXISTS ix_chunks_source_plugin_source_id")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP INDEX IF EXISTS ix_documents_privacy_status")
    op.execute("DROP INDEX IF EXISTS ix_documents_updated_at")
    op.execute("DROP INDEX IF EXISTS ix_documents_source_plugin")
    op.execute("DROP TABLE IF EXISTS documents")
