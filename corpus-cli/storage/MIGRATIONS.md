# storage

- Keep code minimal and explicit.
- Use structlog, raise explicit exceptions.

## SQLAlchemy storage layout

- ORM models are in `storage/models.py`.
- `DocumentModel` and `ChunkModel` map 1:1 to SQLite tables.
- JSON payloads (`embedding_json`, `metadata_json`) are stored as JSON strings for deterministic serialization.
- `chunks_fts` remains an SQLite FTS5 virtual table managed through raw SQL.

## Migrations workflow (Alembic)

- Alembic config lives in `corpus-agent/alembic.ini`.
- Migration scripts live in `corpus-agent/migrations/versions`.
- Store startup runs `alembic upgrade head` automatically for file-backed DBs.
- If migration fails, code must fail loudly and raise.

Create a new migration:

1. Add model changes in `storage/models.py`.
2. Add a new migration file in `migrations/versions/`.
3. Include SQLite-specific DDL for FTS5 updates using `op.execute(...)` when needed.
4. Keep upgrade/downgrade explicit and minimal.

## Sync cursor strategy

Two methods provide cursors for incremental sync:

`get_indexed_ids(source)` → set[str]
  ID-based cursor. Returns all source_ids already in the index for this source.
  Used by YouTube: the plugin walks the playlist newest-first and skips known IDs,
  so each sync fetches the next N unindexed videos regardless of their age.
  DO NOT use date-based cursors for YouTube — published_at of every backlog video
  is older than the newest indexed one, so a date filter silently skips everything
  after the first sync.

`get_latest_content_date(source)` → datetime | None
  Date-based cursor. Returns MAX(updated_at) for the source.
  Used by file-based plugins (Obsidian) where mtime is a reliable incremental cursor.

## privacy_status column

Stored on the `documents` table. Values: "public" | "private" | "unlisted" | "unknown".
Populated by the YouTube plugin. NULL for Obsidian documents.
Exposed in SearchResult, list_documents, and get_document* results.
Filterable via SearchFilters.privacy_status.

## sync_failures table

Tracks per-item sync failures across runs.

Columns:
- `source_plugin`, `source_id` (unique pair)
- `error_message`
- `error_type` (`transient` or `permanent`)
- `failed_at`, `retry_count`, `last_retry_at`

Use this table to skip permanent failures in SyncEngine and to support explicit retry commands.
