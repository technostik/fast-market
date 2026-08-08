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
    doc = Document(
        source_plugin="obsidian", source_id="1", title="t", raw_text="hello world"
    )
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
    check.close()

    assert "privacy_status" in cols


def test_replace_chunks_rolls_back_on_error(store):
    doc = Document(source_plugin="obsidian", source_id="1", title="t", raw_text="hello")
    store.upsert_document(doc, "h1")
    store.replace_chunks(
        "obsidian", "1", [Chunk("obsidian", "1", 0, "base", "c1", [1.0, 0.0])]
    )

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
    store = SQLiteStore(str(db_path))
    conn = sqlite3.connect(db_path)
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    conn.close()
    assert version is not None
    assert store.status() == []


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


def test_status_includes_sync_error_stats(store):
    store.record_failure("youtube", "v1", "boom", "transient")
    store.record_failure("youtube", "v2", "missing transcript", "permanent")

    rows = store.status()
    youtube = next(row for row in rows if row["source_plugin"] == "youtube")
    assert youtube["docs"] == 0
    assert youtube["sync_failures_total"] == 2
    assert youtube["sync_failures_transient"] == 1
    assert youtube["sync_failures_permanent"] == 1


# ── Field definition (soft columns) ─────────────────────────────────────────


def _doc(store, source_id, metadata=None):
    doc = Document(
        source_plugin="youtube",
        source_id=source_id,
        handle=f"yt-{source_id}",
        title=f"title-{source_id}",
        raw_text="body",
        metadata=metadata or {},
    )
    assert store.upsert_document(doc, f"h-{source_id}") is True


def test_field_definition_crud(store):
    created = store.create_field_definition(
        "topic", applies_to="youtube", description="main topic"
    )
    assert created["name"] == "topic"
    assert created["applies_to"] == "youtube"

    listed = store.list_field_definitions()
    assert [f["name"] for f in listed] == ["topic"]

    fetched = store.get_field_definition("topic")
    assert fetched["description"] == "main topic"

    assert store.delete_field_definition("topic") is True
    assert store.get_field_definition("topic") is None
    assert store.list_field_definitions() == []


def test_field_definition_duplicate_raises(store):
    store.create_field_definition("topic")
    with pytest.raises(ValueError, match="already defined"):
        store.create_field_definition("topic")


def test_field_definition_invalid_name_raises(store):
    with pytest.raises(ValueError, match="Invalid field name"):
        store.create_field_definition("Bad Name")
    with pytest.raises(ValueError, match="Invalid field name"):
        store.create_field_definition("with-dash")


def test_set_document_field_refuses_undeclared(store):
    _doc(store, "v1")
    with pytest.raises(ValueError, match="not defined"):
        store.set_document_field("youtube", "v1", "topic", "AI")


def test_set_document_field_missing_document(store):
    store.create_field_definition("topic")
    assert store.set_document_field("youtube", "missing", "topic", "AI") is False


def test_get_documents_missing_field_and_set(store):
    store.create_field_definition("topic")
    _doc(store, "v1")
    _doc(store, "v2")

    missing = store.get_documents_missing_field("topic")
    assert {d["source_id"] for d in missing} == {"v1", "v2"}

    assert store.set_document_field("youtube", "v1", "topic", "AI") is True
    missing = store.get_documents_missing_field("topic")
    assert [d["source_id"] for d in missing] == ["v2"]

    stored = store.get_document("youtube", "v1")
    assert stored["metadata"]["topic"] == "AI"


def test_get_documents_missing_field_source_filter(store):
    store.create_field_definition("topic")
    _doc(store, "v1")
    obs = Document(
        source_plugin="obsidian",
        source_id="n1",
        handle="ob-n1",
        title="note",
        raw_text="body",
    )
    store.upsert_document(obs, "h-n1")

    missing = store.get_documents_missing_field("topic", source="youtube")
    assert [d["source_id"] for d in missing] == ["v1"]
    assert all(d["source_plugin"] == "youtube" for d in missing)


def test_get_documents_missing_field_undeclared_raises(store):
    with pytest.raises(ValueError, match="not defined"):
        store.get_documents_missing_field("topic")


def test_list_documents_extended_order_by_field(store):
    store.create_field_definition("topic")
    _doc(store, "v1", metadata={"topic": "zebra"})
    _doc(store, "v2", metadata={"topic": "apple"})

    docs = store.list_documents_extended(order_by="field:topic", reverse=False)
    assert [d["source_id"] for d in docs] == ["v1", "v2"]

    docs_rev = store.list_documents_extended(order_by="field:topic", reverse=True)
    assert [d["source_id"] for d in docs_rev] == ["v2", "v1"]


def test_list_documents_extended_order_by_undeclared_field_raises(store):
    with pytest.raises(ValueError, match="not defined"):
        store.list_documents_extended(order_by="field:topic")


def test_migration_adds_field_definitions_table(tmp_path):
    db_path = tmp_path / "pre-field.db"
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

    store = SQLiteStore(str(db_path))
    store.create_field_definition("topic")

    check = sqlite3.connect(db_path)
    tables = {
        row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    check.close()

    assert "field_definitions" in tables
    assert store.list_field_definitions()[0]["name"] == "topic"


def _legacy_db_with_row(db_path):
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
    conn.execute(
        "INSERT INTO documents (handle, source_plugin, source_id, title, raw_text, content_hash, metadata_json) "
        "VALUES ('yt-v1', 'youtube', 'v1', 'My Video', 'body text', 'h1', '{}')"
    )
    conn.commit()
    conn.close()


def test_migration_backs_up_existing_db_with_data(tmp_path):
    db_path = tmp_path / "legacy-data.db"
    _legacy_db_with_row(db_path)

    SQLiteStore(str(db_path))

    backup_dir = tmp_path / "backups"
    backups = sorted(backup_dir.glob("legacy-data.pre-migration-*.db"))
    assert len(backups) == 1

    backup = sqlite3.connect(backups[0])
    row = backup.execute(
        "SELECT source_id, title FROM documents WHERE source_plugin='youtube'"
    ).fetchone()
    backup.close()
    assert row == ("v1", "My Video")


def test_migration_does_not_backup_when_already_at_head(tmp_path):
    db_path = tmp_path / "current.db"
    SQLiteStore(str(db_path))

    SQLiteStore(str(db_path))

    assert not (tmp_path / "backups").exists()


def test_backup_prunes_to_newest_five(tmp_path):
    from common.storage.base import backup_sqlite_db

    db_path = tmp_path / "prune.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()

    for _ in range(7):
        backup_sqlite_db(db_path, "test")

    backups = sorted((tmp_path / "backups").glob("prune.pre-migration-*.db"))
    assert len(backups) == 5
