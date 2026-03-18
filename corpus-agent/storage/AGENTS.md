# corpus-agent/storage

## 🎯 Purpose
Provides the persistence layer for document storage, chunk management, and sync tracking using SQLite with SQLAlchemy ORM and Alembic migrations.

## 🏗️ Essential Components
- `models.py` — SQLAlchemy ORM models for documents, chunks, and sync failures (1:1 mapping to SQLite tables)
- `sqlalchemy_store.py` — Main store implementation with session management, CRUD operations, and search methods
- `sqlite_store.py` — Legacy compatibility wrapper (deprecated, raises warning)
- `env.py` — Alembic environment configuration for migrations
- `script.py.mako` — Template for generating new migration scripts

## 📋 Core Responsibilities
- Persist documents with their metadata and content hashes for change detection
- Manage chunk storage including embeddings for semantic search (embedding_json stored as JSON string)
- Maintain FTS5 virtual tables for keyword search through raw SQL
- Track sync failures with retry counts and error types (transient/permanent)
- Handle database migrations through Alembic (auto-run on startup)
- Provide cursor strategies for incremental sync:
  - ID-based (`get_indexed_ids()`) — for YouTube to walk playlist newest-first
  - Date-based (`get_latest_content_date()`) — for file-based plugins using mtime
- Store and filter by privacy status ("public" | "private" | "unlisted" | "unknown") for YouTube content

## 🔗 Dependencies & Integration
- Imports from: `core.models`, `core.paths`, `alembic`, `sqlalchemy`, `structlog`
- Used by: SyncEngine, CLI commands, plugin system (YouTube, Obsidian, etc.)
- External deps: SQLAlchemy, Alembic, sqlite3 (via Python stdlib)

## ✅ Do's
- Keep code minimal and explicit
- Use structlog for all logging
- Use context managers for sessions to ensure proper cleanup
- Store JSON payloads as deterministic JSON strings (`json.dumps()` with default args)
- Include explicit error handling and fail loudly on migration failures
- Use content hashes to detect changes before updating
- Keep migration scripts explicit and minimal
- Use `op.execute()` for SQLite-specific DDL (FTS5 virtual tables)
- Apply filters at the database level when possible (defer to Python only when necessary)
- Return `bool` from upsert operations to indicate whether changes occurred
- Use ID-based cursors for YouTube, date-based for file plugins
- Make privacy_status nullable (NULL for Obsidian, populated for YouTube)

## ❌ Don'ts
- Don't use raw SQLite store directly (SQLiteStore is deprecated)
- Don't ignore migration failures — raise RuntimeError with explicit context
- Don't use date cursors for YouTube sync (will silently skip backlog)
- Don't store Python objects directly — serialize to JSON first
- Don't forget to update FTS tables when chunks change (delete + insert)
- Don't assume all documents have privacy_status (check for NULL)
- Don't use `autocommit=True` — manage transactions explicitly with session.commit()/rollback()
- Don't swallow exceptions in store methods — let them bubble up

## 🛠️ Extension Points
- To add a new model: Define in `models.py`, create migration, add store methods
- To modify search behavior: Extend `SearchFilters` and update `keyword_search`/`semantic_search`
- To add new cursor strategy: Add method to store (e.g., `get_indexed_timestamps()`)
- To add document metadata: Update `DocumentModel`, create migration, update `_row_to_doc_dict()`
- To support new filter types: Add to `SearchFilters` and implement in relevant methods

## 📚 Related Documentation
- See `AGENTS.md` (root) for sync cursor strategy and privacy_status semantics
- See `MIGRATIONS.md` for more details
- Refer to `GOLDEN_RULES.md` for principles: DRY, KISS, CODE IS LAW, FAIL LOUDLY, modularity, granularity, observability
- See plugin-specific AGENTS.md files for how storage is used by each plugin type
