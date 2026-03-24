# /main Module

## 🎯 Purpose
Entry point for the CLI application that orchestrates plugin discovery, command registration, and execution with minimal overhead and explicit error handling.

## 🏗️ Essential Components
- `main.py` — CLI entry point using Click framework with plugin-based command architecture
- `@click.group()` — Main CLI group that aggregates all discovered commands
- `_load()` function — Initialization sequence that configures logging and discovers plugins/commands
- `ctx.obj` — Context object for passing configuration (verbose flag) to subcommands

## 📋 Core Responsibilities
- Initialize logging with appropriate verbosity levels (CRITICAL by default, configurable via --verbose)
- Load configuration through core.config module
- Discover and load all available plugins from configured paths
- Register discovered commands with the main Click group
- Provide consistent CLI interface with proper context passing

## 🔗 Dependencies & Integration
- Imports from: `core.config`, `core.registry`
- Used by: Executed directly as CLI entry point
- External deps: `click`, `structlog` (via logging config), `logging`

## ✅ Do's
- Keep initialization sequence explicit and minimal
- Use `ctx.obj` for passing shared state to subcommands
- Load configuration before plugin discovery
- Register commands only after successful discovery
- Use logging.CRITICAL for default log level to minimize noise
- Force logging configuration reset with `force=True`

## ❌ Don'ts
- Don't perform any business logic in the entry point
- Don't catch exceptions during plugin discovery - FAIL LOUDLY
- Don't modify discovered commands after registration
- Don't use global variables for application state
- Don't lazy-load plugins after CLI startup

## 🛠️ Extension Points
- To add new commands: Implement them as plugins that register with the command registry
- To modify logging behavior: Adjust `logging.basicConfig()` parameters
- To add pre-execution hooks: Extend the `_load()` function with additional initialization
- To customize plugin discovery: Modify `discover_plugins()` configuration

## 📚 Related Documentation
- See `core/registry.md` for plugin and command discovery mechanics
- Refer to `core/config.md` for configuration loading details
- See Click documentation for CLI group and context management patterns
