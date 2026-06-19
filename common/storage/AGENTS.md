# common/storage

## 🎯 Purpose
Shared SQLAlchemy engine and session factory helpers for any fast-market agent that needs a local SQLite database.

## 🏗️ Essential Components
- `base.py` — engine factories, session factory, transactional context manager, and Alembic migration runner

| Function | Description |
|---|---|
| `create_sqlite_engine(tool_name, db_filename, echo, db_path)` | Create a SQLite engine in `~/.local/share/fast-market/{tool}/` |
| `create_memory_engine(echo)` | Create an in-memory SQLite engine for tests |
| `create_session_factory(engine)` | Create a `sessionmaker` bound to an engine |
| `session_scope(session_factory)` | Context manager: commit on success, rollback on exception |
| `run_alembic_migrations(tool_name, alembic_ini_path, db_url_override)` | Run `alembic upgrade head` for the given tool |

## 📋 Core Responsibilities
- Place each tool's database in its XDG data directory (`get_tool_data_dir(tool_name)`)
- Provide `check_same_thread=False` and `pool_pre_ping=True` for safe concurrent access
- Provide an in-memory engine for unit tests that need SQLAlchemy but not disk I/O
- Wrap Alembic migrations with graceful handling of context-setup errors (common in test environments)

## 🔗 Dependencies & Integration
- Imports from: `common.core.paths` (for XDG data dir), `common.structlog`
- Used by: `corpus-cli`, any CLI that needs a persistent local database
- External deps: `sqlalchemy`, `alembic` (optional — only needed for `run_alembic_migrations`)

## ✅ Do's
- Use `create_sqlite_engine()` so the database lands in the correct XDG path
- Use `session_scope()` for all write operations — guarantees rollback on error
- Use `create_memory_engine()` in tests instead of a temp file

## ❌ Don'ts
- Do not hardcode database file paths — always let `create_sqlite_engine()` resolve the path
- Do not open sessions outside `session_scope()` in production code — you will leak uncommitted transactions

## ⚠️ Pitfalls
- `run_alembic_migrations()` silently skips Alembic context warnings that commonly appear in tests. Real migration failures (non-context errors) are re-raised as `RuntimeError`.
- `QueuePool` is used for file-backed engines. In test environments with rapid open/close cycles, prefer `StaticPool` (already used by `create_memory_engine`).

## 🧪 Tests
- Test files: `tests/` (project root)
- Run with: `pytest tests/`
- Use `create_memory_engine()` for all storage tests — no temp file cleanup needed

## 🔍 Observability
- Key log markers: `creating_sqlite_engine`, `creating_memory_engine`, `migrations_complete`, `migrations_failed`

## 📚 Related Documentation
- See `README.md` for usage and CLI reference
- See `common/core/AGENTS.md` for `get_tool_data_dir()` path conventions
- See `corpus-cli/storage/MIGRATIONS.md` for Alembic migration workflow
