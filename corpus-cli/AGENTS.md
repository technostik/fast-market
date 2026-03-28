# corpus-agent

## 🎯 Purpose
A modular local knowledge indexing and search system that ingests content from multiple sources (YouTube, Obsidian), processes it into searchable chunks with embeddings, and provides CLI, API, and web interfaces for interaction.

## 🏗️ Architecture Overview

```
corpus-agent/
├── core/           # Foundation: config, models, embedding, sync engine
├── storage/        # Persistence: SQLite with SQLAlchemy + Alembic
├── plugins/        # Source integrations: YouTube, Obsidian
├── commands/       # CLI modules (see below)
├── api/            # HTTP endpoints (via server.py)
├── ui/             # Frontend HTML pages
└── cli/            # Entry point (main.py)
```

## CLI Commands

### Core Commands

| Command | Description |
|---------|-------------|
| `corpus sync` | Fetch content and index into corpus |
| `corpus search` | Search indexed documents |
| `corpus list` | List indexed documents |
| `corpus get-from-id` | Get document by handle |
| `corpus get-from-source` | Get document by source + id |
| `corpus get-last` | Get most recently indexed document |
| `corpus delete` | Delete document by handle |
| `corpus status` | Show corpus statistics |
| `corpus serve` | Start web server |
| `corpus embed-server` | Start embedding server |

### Sync Modes

The `corpus sync` command supports three modes:

- `new` (default) — Sync only new items, skip already-indexed
- `backfill` — Re-fetch all items, ignore previous indexing
- `reindex` — Regenerate embeddings for existing documents (no content re-fetch)

```bash
corpus sync                          # new items only (default)
corpus sync --mode backfill          # re-fetch all content
corpus sync --mode reindex           # regenerate embeddings
```

### Retry Failures

Use `--retry-failure` to clear tracked sync failures before syncing:

```bash
corpus sync --retry-failure                      # retry transient failures
corpus sync --retry-failure --clear-permanent    # include permanent failures
corpus sync --retry-failure --include-blocked   # include blocked videos
```

### Setup Commands

```bash
corpus setup run    # Run interactive setup wizard
corpus setup edit  # Interactively edit config.yaml
```

## 📋 Core System Responsibilities

### Data Ingestion Pipeline
- Discover content items from plugins via `list_items()` with cursor-based incremental sync
- Fetch full document content via plugin `fetch()` methods
- Chunk documents into manageable pieces with overlap for context preservation
- Generate embeddings for semantic search (with server/local fallback)
- Store documents, chunks, and metadata in SQLite with FTS5 for keyword search

### Plugin Architecture
- **SourcePlugin** ABC defines contract: `list_items()` + `fetch()`
- Each plugin provides:
  - Core indexing logic (required)
  - Optional CLI options (injected into relevant commands)
  - Optional API routers (mounted under plugin name)
  - Optional frontend JS fragments
- Dynamic discovery via `core.registry` (fails loudly on misconfiguration)

### Storage Layer
- SQLAlchemy ORM models: Document, Chunk, SyncFailure
- FTS5 virtual tables for keyword search (via raw SQL)
- Alembic migrations (auto-run on startup)
- Cursor strategies:
  - ID-based for YouTube (newest-first playlist walking)
  - Date-based for file plugins (mtime tracking)
- Privacy status tracking for YouTube content

### User Interfaces
- **CLI**: Click-based with dynamic plugin option injection
- **API**: FastAPI server with auto-discovered endpoints
- **Web UI**: Vanilla HTML/JS with source color-coding (Obsidian/Yellow)

## 🔗 Component Dependencies

```
CLI (main.py) → Registry → Commands → Core → Storage
                      ↘ Plugins ↗
                      
Server (server.py) → Registry → API Routers → Core → Storage
                           ↘ Frontend JS fragments

Core → Embedder (server/local fallback)
     → SyncEngine (orchestrates plugins + storage)
     → Config/Paths (XDG-compliant)
```

## ✅ System-Wide Do's

### Architecture & Design
- **Use XDG paths everywhere**: Config in `~/.config/fast-market/`, data in `~/.local/share/fast-market/`
- **Keep modules focused**: One responsibility per module (core/plugins/commands/storage/ui)
- **Use structlog for all logging** with consistent field names
- **Return structured data** from commands, format via `helpers.out()`
- **Use dataclasses with slots** for memory efficiency with many items

### Plugin Development
- Pass `known_id_dates` to `list_items()` for incremental decisions
- Include `updated_at` in ItemMeta when available
- Raise typed exceptions with clear retry policies (permanent/transient)
- Document performance characteristics (API rate limits, file system assumptions)

### Storage Implementation
- Use context managers for SQLAlchemy sessions
- Store JSON as deterministic strings (`json.dumps()` with default args)
- Update FTS tables when chunks change (delete + insert)
- Return bool from upsert to indicate changes

### Command Implementation
- Build plugin options dynamically from manifests (never hardcode plugin names)
- Use `ctx.obj` for global options (`--verbose`, `--format`)
- Delegate business logic to core components (commands are thin orchestrators)
- Raise explicit exceptions with clear messages

### CLI Syntax Conventions
All commands must follow standard short form conventions:

| Option | Short | When to Use |
|--------|-------|-------------|
| `--format` | `-F` | All data output commands (search, list, sync, etc.) |
| `--limit` | `-l` | Commands with pagination or item limits |
| `--port` | `-p` | Server commands |
| `--model` | `-m` | Model-related commands |

```python
# CORRECT: Include standard short forms
@click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.option("--limit", "-l", type=int, default=10)

# INCORRECT: Missing short form (violates standard)
@click.option("--format", "fmt", ...)
@click.option("--limit", type=int, ...)
```

### Server & API
- Load plugins/commands dynamically at startup
- Serve UI files read-only from filesystem
- Return proper HTTP status codes with error details

## ❌ System-Wide Don'ts

### Never
- **Hardcode paths** — always use `core.paths`
- **Hardcode plugin names** like `["obsidian", "youtube"]` — use manifests
- **Swallow exceptions** during plugin discovery/registration (FAIL LOUDLY)
- **Use generic exceptions** — always use typed errors from `sync_errors.py`
- **Store Python objects directly** in DB — serialize to JSON first
- **Use date cursors for YouTube sync** (will silently skip backlog)
- **Assume plugins exist** — check manifests and handle gracefully
- **Modify plugin manifests** — they are read-only inputs
- **Block server startup** if a plugin fails — log and continue
- **Expose sensitive data** in frontend code

### Avoid
- **Mixing concerns** — keep embedding in embedder.py, sync in sync_engine.py
- **Business logic in commands** — keep them as thin orchestrators
- **Lazy-loading plugins** after CLI startup
- **Autocommit=True** in SQLAlchemy — manage transactions explicitly
- **Raw SQLite store** (deprecated)
- **External JS libraries** in UI — vanilla JS only

## 🛠️ Extension Points

### Add New Source Plugin
1. Subclass `SourcePlugin` in `plugins/your_plugin/`
2. Implement `list_items()` with appropriate cursor strategy
3. Implement `fetch()` returning `Document`
4. Add CLI options via `PluginManifest.cli_options`
5. Add API router via `PluginManifest.api_router` (optional)
6. Add frontend JS via `PluginManifest.frontend_js` (optional)

### Add New Command
1. Create `commands/your_command/` with `__init__.py` and `register.py`
2. Implement `register(plugin_manifests) -> CommandManifest`
3. Define base Click options (include `-F` for `--format`, `-l` for `--limit`)
4. Add API router via `CommandManifest.api_router` (optional)
5. Add frontend JS via `CommandManifest.frontend_js` (optional)
6. Registry auto-injects plugin options and registers command

### Add Subcommand to Existing Group
For commands that need subcommands (like `setup`):
1. Create `commands/parent_command/subcommands/your_subcommand.py`
2. Implement `register(plugin_manifests) -> click.Command`
3. Parent command auto-discovers and adds subcommands

### Add New UI Feature
1. Add HTML page to `ui/` directory
2. Add route in `server.py` using `_html()` helper
3. Fetch data from existing API endpoints
4. Use source color-coding variables from `:root`
5. Add frontend fragments via `/api/frontend-fragments` if needed

### Extend Storage
1. Add/modify models in `storage/models.py`
2. Create Alembic migration
3. Update store methods in `sqlalchemy_store.py`
4. Add cursor strategy methods if needed
5. Update FTS triggers if modifying chunk table

### Modify Embedding Pipeline
1. Update model params in `core/embedder.py`
2. Modify server communication in `_embed_via_server()`
3. Adjust chunking strategy in `sync_engine.chunk_by_sections()`
4. Update cache invalidation logic

## 📚 Related Documentation

- `GOLDEN_RULES.md` — Core principles: DRY, KISS, CODE IS LAW, FAIL LOUDLY, modularity, granularity, observability
- `AGENTS.md` in each subdirectory for component-specific guidelines:
  - `core/AGENTS.md` — Foundation, embedding, sync engine
  - `storage/AGENTS.md` — Persistence, migrations, cursors
  - `plugins/AGENTS.md` — Source plugin interface
  - `commands/AGENTS.md` — CLI command architecture
  - `ui/AGENTS.md` — Frontend pages and interactions
  - `server/AGENTS.md` — HTTP server and API mounting

## 🔍 Key Design Decisions

### Why SQLite + SQLAlchemy + Alembic?
- Zero-config local database with migrations for schema evolution
- FTS5 for keyword search, JSON for embedding storage
- SQLAlchemy provides ORM convenience while allowing raw SQL for FTS

### Why Plugin-Based Architecture?
- Each source has unique requirements (YouTube API auth, Obsidian filesystem)
- Enables independent development and testing
- CLI options and API routes auto-discovered

### Why Two Search Modes?
- Keyword search via FTS5 for exact matches
- Semantic search via embeddings for concept matching
- UI presents both with unified results

### Why Server Fallback for Embeddings?
- Keep model loaded in memory for performance
- Fall back to local if server unavailable
- Normalized vectors for cosine similarity

### Why Multiple Cursor Strategies?
- YouTube needs ID-based to walk playlists newest-first
- File plugins use mtime for efficient rescans
- Storage layer provides both patterns
