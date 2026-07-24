"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-24
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
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(name)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_collections_name ON collections(name)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            handle TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(handle)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_documents_handle ON documents(handle)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents(content_hash)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tree_nodes (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            node_id TEXT NOT NULL,
            parent_id INTEGER REFERENCES tree_nodes(id) ON DELETE SET NULL,
            title TEXT NOT NULL DEFAULT '',
            start_index INTEGER NOT NULL DEFAULT 0,
            end_index INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            order_index INTEGER NOT NULL DEFAULT 0,
            tags TEXT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tree_nodes_document_id ON tree_nodes(document_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tree_nodes_node_id ON tree_nodes(node_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tree_nodes_parent_id ON tree_nodes(parent_id)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS collection_members (
            id INTEGER PRIMARY KEY,
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            root_node_id INTEGER REFERENCES tree_nodes(id) ON DELETE SET NULL,
            added_at TEXT NOT NULL,
            UNIQUE(collection_id, document_id, root_node_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_collection_members_collection_id
        ON collection_members(collection_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_collection_members_document_id
        ON collection_members(document_id)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS index_runs (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            model_used TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            error TEXT,
            is_ephemeral INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_index_runs_document_id ON index_runs(document_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_index_runs_status ON index_runs(status)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS index_runs")
    op.execute("DROP TABLE IF EXISTS collection_members")
    op.execute("DROP TABLE IF EXISTS tree_nodes")
    op.execute("DROP TABLE IF EXISTS documents")
    op.execute("DROP TABLE IF EXISTS collections")
