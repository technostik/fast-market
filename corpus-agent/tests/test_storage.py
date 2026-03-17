from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy.exc import IntegrityError

from core.models import Chunk, Document
from storage.sqlite_store import SQLiteStore


def test_upsert_idempotent(store):
    doc = Document(source_plugin="obsidian", source_id="1", title="t", raw_text="hello")
    assert store.upsert_document(doc, "h1") is True
    assert store.upsert_document(doc, "h1") is False


def test_keyword_search(store):
    doc = Document(source_plugin="obsidian", source_id="1", title="t", raw_text="hello world")
    store.upsert_document(doc, "h1")
    chunk = Chunk("obsidian", "1", 0, "hello world", "c1", [1.0, 0.0])
    store.replace_chunks("obsidian", "1", [chunk])
    results = store.keyword_search("hello", 5)
    assert len(results) == 1


def test_auto_migration_adds_privacy_status(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            handle TEXT NOT NULL,
            source_plugin TEXT NOT NULL,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            url TEXT,
            updated_at TEXT,
            duration_seconds INTEGER,
            content_hash TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            UNIQUE(source_plugin, source_id),
            UNIQUE(handle)
        );
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            source_plugin TEXT NOT NULL,
            source_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            UNIQUE(source_plugin, source_id, chunk_index)
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(source_plugin, source_id, content);
        """
    )
    conn.commit()
    conn.close()

    SQLiteStore(str(db_path))

    check = sqlite3.connect(db_path)
    cols = {row[1] for row in check.execute("PRAGMA table_info(documents)").fetchall()}
    version = check.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    check.close()

    assert "privacy_status" in cols
    assert version == "0001_initial_schema"


def test_replace_chunks_rolls_back_on_error(store):
    doc = Document(source_plugin="obsidian", source_id="1", title="t", raw_text="hello")
    store.upsert_document(doc, "h1")
    store.replace_chunks("obsidian", "1", [Chunk("obsidian", "1", 0, "base", "c1", [1.0, 0.0])])

    with pytest.raises(IntegrityError):
        store.replace_chunks(
            "obsidian",
            "1",
            [
                Chunk("obsidian", "1", 0, "dup-a", "c2", [0.1, 0.9]),
                Chunk("obsidian", "1", 0, "dup-b", "c3", [0.2, 0.8]),
            ],
        )

    results = store.semantic_search([1.0, 0.0], 5)
    assert len(results) == 1
    assert results[0].excerpt == "base"


def test_migration_works_when_cwd_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "cwd-change.db"
    SQLiteStore(str(db_path))
    conn = sqlite3.connect(db_path)
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    conn.close()
    assert version == "0001_initial_schema"


def test_failure_tracking_methods(store):
    store.record_failure("youtube", "v1", "boom", "transient")
    store.record_failure("youtube", "v1", "boom again", "transient")
    rows = store.list_failures("youtube")
    assert len(rows) == 1
    assert rows[0]["retry_count"] == 1

    store.record_failure("youtube", "v2", "missing transcript", "permanent")
    assert store.get_permanent_failures("youtube") == {"v2"}

    store.clear_failure("youtube", "v1")
    remaining = store.list_failures("youtube")
    assert len(remaining) == 1
    assert remaining[0]["source_id"] == "v2"


def test_auto_migration_adds_sync_failures_for_existing_0001_db(tmp_path):
    db_path = tmp_path / "legacy-0001.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE documents (
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
        );
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            source_plugin TEXT NOT NULL,
            source_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            UNIQUE(source_plugin, source_id, chunk_index)
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(source_plugin, source_id, content);
        CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY);
        INSERT INTO alembic_version(version_num) VALUES ('0001_initial_schema');
        """
    )
    conn.commit()
    conn.close()

    SQLiteStore(str(db_path))

    check = sqlite3.connect(db_path)
    tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    version = check.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    check.close()

    assert "sync_failures" in tables
    assert version == "0002_add_sync_failures_table"
