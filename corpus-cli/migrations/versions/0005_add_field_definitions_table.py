"""add field_definitions table

Revision ID: 0005_add_field_definitions_table
Revises: 0004_add_pool_items_table
Create Date: 2026-08-08
"""

from __future__ import annotations

from alembic import op

revision = "0005_add_field_definitions_table"
down_revision = "0004_add_pool_items_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Pure additive DDL: no existing column is touched. field_definitions only
    # declares soft fields; document values live in documents.metadata_json.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            applies_to TEXT NOT NULL DEFAULT 'all',
            description TEXT,
            created_at TEXT NOT NULL,
            CONSTRAINT uq_field_definitions_name UNIQUE (name)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field_definitions")
