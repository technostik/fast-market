# commands/

## 🎯 Purpose
Provides a self-contained, plugin-agnostic command module system where each subdirectory implements a complete CLI command with optional API and frontend extensions, dynamically integrating plugin-specific options at runtime.

## 🏗️ Essential Components
- `__init__.py` — Empty marker file that identifies a command directory
- `register.py` — Exports `register(plugin_manifests: dict) -> CommandManifest`; declares base Click options and returns the complete command manifest
- `AGENTS.md` — Documents the command's purpose, behavior, and extension points
- `base.CommandManifest` — Dataclass containing command name, Click command object, optional API router, and optional frontend JS snippet
- `helpers.py` — Shared utilities for commands: engine building, output formatting, logging configuration, filter construction

## 📋 Core Responsibilities
- Implement complete CLI commands that operate on multiple plugins generically
- Declare base Click options specific to the command's functionality
- Accept plugin manifests and use them to inject plugin-specific CLI options dynamically
- Provide optional FastAPI routers for REST API endpoints
- Supply optional frontend JavaScript for web interface integration
- Handle command execution with proper error handling and logging
- Format output according to global `--format` flag (JSON or text)
- Respect global options (`--verbose`, `--format`) via Click context

## 🔗 Dependencies & Integration
- Imports from: `core.config`, `core.embedder`, `core.registry`, `core.sync_engine`, `storage.sqlite_store`, `click`, `structlog`, `fastapi` (optional)
- Used by: `cli/main.py` (root Click group), CLI entry point, API router registration
- External deps: `click` (CLI framework), `structlog` (structured logging), `fastapi` (optional API endpoints)

## ✅ Do's
- Iterate over `plugin_manifests.keys()` when building plugin-specific options like `--source`
- Use `ctx.obj` to access global options (`verbose`, `format`) — never re-declare them
- Extend command params with plugin options via `command.params.extend(plugin_manifest.cli_options.get(cmd_name, []))`
- Use `helpers.build_engine()` to construct the engine, plugins, and store with proper logging configuration
- Return structured data from command functions and use `helpers.out()` for consistent formatting
- Raise explicit exceptions with clear error messages (fail loudly)
- Use `structlog` for all logging with appropriate context
- Keep commands focused on orchestration — delegate business logic to core components

## ❌ Don'ts
- NEVER import plugin names directly (e.g., `obsidian`, `youtube`) — always use the plugin manifests
- NEVER hardcode plugin lists like `["obsidian", "youtube"]` — build dynamically from `plugin_manifests`
- NEVER re-declare global options (`--verbose`, `--format`) in command decorators
- NEVER assume a specific plugin exists — check manifests and handle missing plugins gracefully
- NEVER modify plugin manifests — they are read-only inputs
- NEVER leak implementation details across command boundaries
- DON'T put business logic in commands — keep them as thin orchestration layers

## 🛠️ Extension Points
- **To add a new command**: Create a new subdirectory with `__init__.py` and `register.py` implementing the `register()` function returning `CommandManifest`. Define base options in Click decorators. The registry will automatically inject plugin options and make it available.
- **To add API endpoints**: Include a FastAPI `APIRouter` in the manifest via `api_router` field. The registry will mount it under the command's name.
- **To add frontend integration**: Provide JavaScript snippet in `frontend_js` field. The web interface will inject it when rendering command-related pages.
- **To modify option injection**: The injection happens in the registry — ensure `plugin_manifest.cli_options` contains the correct mapping from command name to list of Click options.
- **To add new shared helpers**: Extend `helpers.py` with reusable utilities, keeping them focused and well-documented.

## 📚 Related Documentation
- See `GOLDEN_RULES.md` for architectural principles (DRY, KISS, CODE IS LAW, FAIL LOUDLY)
- See `cli/main.py` for how commands are registered with the root Click group
- See `core/registry.py` for plugin option injection mechanism
- See `[any command directory]/AGENTS.md` for specific command implementations (sync, search, reindex, etc.)
- See `AGENTS.md` (root) for overall project structure and agent guidelines
