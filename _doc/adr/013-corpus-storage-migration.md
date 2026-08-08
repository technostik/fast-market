# ADR 013: Corpus storage migration — SQLAlchemy + Alembic with pre-migration backups

## Status

Accepted

## Context

The corpus tool originally persisted through a raw-SQLite `SQLiteStore`
(`corpus-cli/storage/sqlite_store.py`) that managed its tables by hand. The
schema was implicit (embedded `CREATE TABLE` DDL), so there was:

- **no schema versioning** — no way to evolve the database between releases
  without destructive ad-hoc SQL;
- **no migration safety** — upgrading the store meant hoping the new DDL
  matched what was already on disk, with no snapshot to fall back to;
- **no extension path for metadata** — features like per-document soft fields,
  a sync pool, and failure tracking each needed new tables/columns, which
  threatened to hard-code the schema further.

At the same time the corpus data model needed to grow in four directions:

1. **Pool-based sync** — `corpus scan` inventories a source and queues items in
   a `pool_items` table; `corpus sync` processes the pool. Items that change
   state (e.g. a YouTube video becoming public) must be re-queued automatically.
2. **Soft fields** — arbitrary named values attached to documents (summary,
   tags, …). They must be declared, queryable ("documents missing this field"),
   sortable, and fillable by LLM-backed *operations* — without a column per
   field and without a migration per field.
3. **Quota-aware errors** — the YouTube API quota boundary must be a typed,
   transient error carrying `Retry-After`, not a `RuntimeError` detected by
   string-matching `"quota"`.
4. **A restorable data guarantee** — the user explicitly required that
   migrating an existing, already-synced corpus **must not risk losing data**:
   "the migration does a backup before migrating data."

The old store also had pre-existing test failures (API `/sync` endpoint gone,
CLI output polluted by structlog to stdout, stale tests) that needed to be
fixed as part of landing the new storage.

## Decision

### 1. SQLAlchemy ORM + Alembic as the storage layer

- ORM models live in `corpus-cli/storage/models.py` (`DocumentModel`,
  `ChunkModel`, `SyncFailureModel`, `PoolItemModel`, `FieldDefinitionModel`)
  mapping 1:1 to SQLite tables; JSON payloads (`embedding_json`,
  `metadata_json`) are stored as deterministic JSON strings.
- `storage/sqlalchemy_store.py` is the real implementation. `sqlite_store.py`
  is kept only as a **deprecated compatibility wrapper** that warns and
  delegates, so existing callers/tests keep working during the transition.
- Schema changes are **Alembic migrations** in `corpus-cli/migrations/versions/`
  (`0001` initial, `0002` sync_failures, `0003` vault_path on failures, `0004`
  pool_items, `0005` field_definitions). Startup runs `alembic upgrade head`
  automatically for file-backed DBs; a failed migration raises (FAIL LOUDLY).

### 2. Pre-migration backup (the data guarantee)

`common/storage/base.py` grows `run_alembic_migrations()` orchestration:

- Before upgrading an existing file-backed DB, write a **consistent snapshot**
  via the sqlite3 *online backup API* to
  `<db_dir>/backups/<name>.pre-migration-<timestamp>.db`.
- Keep only the newest **5** backups; timestamp carries microseconds so
  same-second runs never collide.
- **No backup** is created when the DB is already at the head revision (checked
  against `alembic_version` vs `ScriptDirectory.get_heads()`) or does not exist
  yet — so routine startups on a current DB don't accumulate snapshots.
- If the snapshot cannot be written, **migration is not attempted** (FAIL
  LOUDLY). This is the behavior the user asked for: synced data is never at
  risk when a migration runs.

### 3. Pool-based sync workflow (`0004 pool_items`)

- `corpus scan` walks a source's full inventory and stores each item in
  `pool_items` (`pending`), keeping `metadata_json` current. Re-running scan
  refreshes metadata of pending/failed items so state changes are seen.
- `corpus sync` drains the pool. When the pool is empty it **falls back to a
  direct incremental `engine.sync()`** so `corpus sync` keeps working without a
  prior `corpus scan` (pool workflows still win when items are waiting).
- Plugins declare `requeue_on` (e.g. YouTube: a `failed` item whose
  `privacy_status` becomes `public` is reset to `pending`), implemented
  generically in the scan path.

### 4. Generic scan generalization

- Plugins declare a `scan_strategy`; the scan command dispatches on it:
  `tui` (Obsidian interactive vault walk) vs `generic` (any plugin whose
  `list_items` supports `scan_all=True`). A `--auto` flag forces the generic
  path, skipping the TUI.
- The YouTube-specific scan is replaced by the generic `_scan_source`, keyed on
  metadata refresh rather than privacy-only logic.

### 5. Soft fields declared, values in JSON (`0005 field_definitions`)

- `field_definitions` **declares** fields (`name`, `applies_to`, `description`).
  Values are never columns — they live in `documents.metadata_json` under the
  field name. Adding a field is a row insert, not a migration.
- Field names are validated against `^[a-z][a-z0-9_]*$` because they become
  `json_extract(metadata_json, '$.<name>')` paths.
- The store enforces declarations: `get_documents_missing_field()`,
  `set_document_field()` and `order_by="field:<name>"` fail loudly if the field
  is not declared. `corpus field create|list|delete|missing|set` drives it.

### 6. Operations compute field values

- `corpus-cli/operations/` hosts `Operation` subclasses (summarize, tag) that
  compute one field from a document dict; each exposes an `OperationManifest`
  (name, field, `applies_to`).
- Operations declare `requires` (input fields); absence raises
  `MissingInputFieldError` (permanent) instead of a generic exception.
- `corpus sync --field <name> [--handles ...]` runs the registered operation on
  documents missing that field via `SyncEngine.sync_field()`, recording
  failures through the normal failure machinery.

### 7. Typed, quota-aware error taxonomy

- `APIRateLimitError` (transient) carries `retry_after_seconds` /
  `quota_reset_at` extracted from the API response; the YouTube plugin raises
  it when `_is_quota_exceeded_error()` matches, and commands map it to a clean
  `click.ClickException` / HTTP 429. No more string-matching on `"quota"`.
- `MissingInputFieldError` (permanent) added.
- Transcript failure classification is corrected: a genuinely missing transcript
  raises permanent `TranscriptUnavailableError` (so sync stops retrying), while
  transient causes (IP block, quota, network) still raise retryable
  `VideoBlockedError`.

### 8. RESTored API surface + test hardening

- `POST /sync` is back in `commands/sync/register.py` via a `_SyncRequest`
  pydantic model (`mode=new|backfill|reindex`, `retry_failure`,
  `clear_permanent`, `non_public`), 400 on unknown source, 429 on quota.
- Fixes: real-structlog stdout leak in `commands/helpers.py`, order-dependent
  config tests, and the pre-existing test failures; new suites cover the backup
  behavior, field CLI, generic scan, sync engine, API, and CLI.

## Rationale

**Why SQLAlchemy + Alembic rather than hand-written DDL?** Schema evolution is
now versioned and additive — each migration is a reviewable file, downgrades
are possible, and new tables (pool, field definitions) ship without risky
ad-hoc SQL against live databases.

**Why the sqlite3 online backup API?** `src.backup(dst)` produces a consistent
snapshot even while the DB is in use, which is exactly the situation at
startup-migration time; it is cheaper and safer than copying the file.

**Why only backup when migrating an existing DB at a non-head revision?**
Routine startups on a current schema shouldn't churn `backups/`; the backup is
a migration-time guarantee, not a general backup policy.

**Why JSON metadata instead of a column per field?** Soft fields are
open-ended; a column per field would spawn a migration per feature and bloat
the schema. Declared names + `json_extract` give typed-ish queries, validation
on write, and indexable ordering without schema changes. The declaration gate
prevents silent typo'd fields.

**Why keep `SQLiteStore` as a deprecated wrapper?** The transition must not
break existing callers/tests mid-migration; the wrapper warns and delegates so
the new store can land incrementally.

**Why a typed `APIRateLimitError`?** String-matching error messages is fragile
across HTTP layers; a typed transient error with a retry policy is checkable at
each boundary (CLI, API, sync engine) and carries the reset time for better
UX.

## Consequences

- Every existing file-backed corpus DB gets a timestamped
  `*.pre-migration-<ts>.db` snapshot in `<db_dir>/backups/` (newest 5 kept) the
  first time a non-head revision is applied — after which startups are silent.
- The deprecated `SQLiteStore` remains importable for compatibility but is not
  to be used by new code.
- Schema now has a single source of truth (`storage/models.py` + migrations);
  adding a table/column is an Alembic revision and a corresponding store
  method.
- Soft fields are declared, queryable, sortable, and fillable by operations,
  all without per-field migrations; undeclared writes fail loudly.
- `corpus scan`/`sync` split is now pool-based with a direct-sync fallback, so
  the pool never becomes a hard prerequisite for syncing.
- The YouTube plugin raises typed errors; quota and transcript-missing failures
  are classified correctly (transient vs permanent) so the retry machinery does
  the right thing.
