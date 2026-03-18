# Core Module

## 🎯 Purpose
Provides the foundational infrastructure, shared utilities, and orchestration logic that all plugins and commands rely upon for document processing, embedding generation, and synchronization.

## 🏗️ Essential Components

### Configuration & Paths
- `config.py` — Loads and resolves YAML configuration from XDG-compliant paths with fallback to legacy locations
- `paths.py` — Manages XDG-compliant directory resolution for config, data, and cache with environment variable overrides

### Document Handling
- `handle.py` — Generates stable, human-readable document handles (e.g., `yt-video-title-a3f2`) from plugin source IDs and titles
- `models.py` — Defines core dataclasses (`Document`, `Chunk`, `SyncResult`, `SearchResult`) shared across all components

### Embedding Infrastructure
- `embedder.py` — Provides embedding generation with automatic fallback from server to local model and text normalization
- `embedding_server.py` — Persistent FastAPI server that keeps sentence-transformers models loaded in memory

### Synchronization
- `sync_engine.py` — Orchestrates the sync process: chunking documents, generating embeddings, and coordinating with storage
- `sync_errors.py` — Defines typed exceptions with retry policies (permanent vs transient failures)

### Plugin Discovery
- `registry.py` — Dynamically discovers and loads plugins and commands, failing loudly on misconfiguration

## 📋 Core Responsibilities
- **Configuration Management**: Load config from XDG-compliant paths with graceful fallback and deprecation warnings
- **Plugin Orchestration**: Discover, load, and coordinate plugins through a unified registry system
- **Document Processing**: Generate stable handles, chunk content, and manage document metadata consistently
- **Embedding Pipeline**: Provide reliable embedding generation with server fallback and normalization
- **Sync Coordination**: Manage the end-to-end sync flow with proper error handling and failure tracking
- **Storage Abstraction**: Define shared data models that all storage implementations must honor

## 🔗 Dependencies & Integration
- **Imports from**: 
  - Standard library: `hashlib`, `pathlib`, `datetime`, `importlib`
  - External: `yaml`, `structlog`, `sentence-transformers` (optional), `fastapi` (server only)
  
- **Used by**:
  - `plugins/` — All source plugins implement the models and use sync engine
  - `commands/` — CLI commands use core for orchestration
  - `storage/` — Storage implementations must honor core models
  - `api/` — Server endpoints use core for search and sync

- **External deps**: 
  - Required: `pyyaml`, `structlog`
  - Optional ML: `sentence-transformers`, `torch`
  - Optional server: `fastapi`, `uvicorn`, `httpx`

## ✅ Do's
- **Use XDG paths**: Always use `paths.py` for directory resolution, never hardcode paths
- **Add deprecation warnings**: When changing config paths or behavior, add clear warnings with stacklevel=2
- **Fail loudly on plugin errors**: Let plugin discovery/registration errors propagate (per FAIL LOUDLY principle)
- **Use typed exceptions**: Define specific error classes with clear retry policies in `sync_errors.py`
- **Log structred data**: Use `structlog` with consistent field names for observability
- **Normalize embeddings**: Always normalize vectors to unit length via `Embedder._normalize()`
- **Cache embeddings**: Use in-memory cache with content hashing to avoid redundant computation

## ❌ Don'ts
- **Don't hardcode paths**: Never use `os.getcwd()` or relative paths; always use `paths.py`
- **Don't swallow plugin errors**: Let registration failures propagate (no silent fallbacks except during transition)
- **Don't mix concerns**: Keep embedding logic in `embedder.py`, sync logic in `sync_engine.py`, models in `models.py`
- **Don't bypass handle generation**: Always use `make_handle()` for document IDs, never generate custom formats
- **Don't ignore embedding server health**: Check server compatibility (model name, loaded status) before use
- **Don't use generic exceptions**: Always raise specific `SyncError` subclasses with proper `permanent` flags

## 🛠️ Extension Points

### To add a new configuration source:
1. Extend `_resolve_config_path()` in `config.py` with new resolution logic
2. Maintain backward compatibility with deprecation warnings
3. Update XDG environment variable handling in `paths.py`

### To modify embedding behavior:
1. Update model parameters in `Embedder.__init__()`
2. Modify server communication in `_embed_via_server()`
3. Adjust chunking strategy in `sync_engine.chunk_by_sections()`

### To add new document metadata:
1. Extend `Document` dataclass in `models.py` with optional fields
2. Update plugin `fetch()` methods to populate new fields
3. Modify storage layer to persist new fields

### To implement new sync strategy:
1. Extend `SyncEngine.sync()` with new mode parameters
2. Update cursor handling in plugin `list_items()` methods
3. Modify failure tracking in `SQLiteStore`

## 📚 Related Documentation
- See `GOLDEN_RULES.md` for core principles (DRY, KISS, CODE IS LAW, FAIL LOUDLY)
- Refer to `plugins/base.py` for plugin interface requirements
- See `storage/sqlite_store.py` for storage implementation details
- Refer to `commands/README.md` for command extension patterns
