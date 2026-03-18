
# core/plugins

## 🎯 Purpose
Provides the plugin system foundation that enables external data sources (YouTube, Obsidian, etc.) to integrate with the document indexing pipeline through a standardized interface.

## 🏗️ Essential Components
- `base.py` — Defines the core plugin interfaces and data structures
- `ItemMeta` — Data class representing metadata about a source item to be indexed
- `SourcePlugin` — Abstract base class that all source plugins must implement
- `PluginManifest` — Container for all plugin contributions (CLI, API, frontend)

## 📋 Core Responsibilities
- Define the contract between the core system and external data source plugins
- Standardize how plugins expose items for indexing (list_items)
- Standardize how plugins fetch full document content (fetch)
- Provide metadata structure for tracking item state (source_id, updated_at)
- Package plugin contributions beyond core indexing (CLI commands, API routes, frontend JS)

## 🔗 Dependencies & Integration
- Imports from: `core.models` (Document)
- Used by: Plugin implementations (YouTubePlugin, ObsidianPlugin), Plugin loader, Indexing engine
- External deps: None (pure ABC and dataclasses)

## ✅ Do's
- Use `slots=True` in dataclasses for memory efficiency with many items
- Pass `known_id_dates` to `list_items` to enable incremental indexing decisions
- Include `updated_at` in ItemMeta when available for change detection
- Raise explicit, domain-specific exceptions with clear error messages
- Use structlog for structured logging in plugin implementations
- Keep plugin interface methods minimal and focused
- Document performance characteristics in plugin implementations (e.g., API rate limits)

## ❌ Don'ts
- Don't add database dependencies to the base plugin classes
- Don't assume synchronous execution — plugins should be async-ready
- Don't modify `known_id_dates` dict — treat as read-only
- Don't add plugin-specific logic to base classes
- Don't swallow exceptions — FAIL LOUDLY with tracebacks
- Don't add business logic to data classes (ItemMeta is for data only)

## 🛠️ Extension Points
- To add new source plugin: Subclass `SourcePlugin`, implement `list_items` and `fetch`
- To add CLI commands: Include `click.Option` objects in `PluginManifest.cli_options`
- To add API endpoints: Provide FastAPI `APIRouter` in `PluginManifest.api_router`
- To add frontend features: Provide JavaScript snippet in `PluginManifest.frontend_js`
- To inject options into all commands: Use `"*"` key in `cli_options` dict
