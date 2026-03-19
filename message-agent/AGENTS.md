# message-agent

## 🎯 Purpose

A modular messaging agent that enables CLI tools to send alerts and receive responses via messaging platforms (starting with Telegram). It allows long-running CLI commands to interact with users through familiar chat interfaces.

## 🏗️ Architecture Overview

```
message-agent/
├── message_entry/       # CLI entry point (NOT cli/!)
├── cli/                 # Click main group + discovery
├── core/                # Config and data models
├── plugins/             # Platform integrations
│   └── telegram/        # Telegram bot implementation
├── commands/            # CLI commands
│   ├── ask/             # Ask question, wait for reply
│   ├── alert/           # Send notification
│   └── setup/           # Configuration wizard
└── common -> ../common   # Shared utilities symlink
```

## 📋 Core System Responsibilities

### Messaging Flow

- **ask**: Send message → Wait for reply (blocking) → Return response
- **alert**: Send message → Optionally wait for acknowledgment → Return status

### Plugin Architecture

- **MessagePlugin** ABC defines contract: `send_message()`, `wait_for_reply()`, `wait_for_any_update()`, `send_alert()`, `test_connection()`
- Each plugin provides:
  - Core messaging logic (required)
  - Optional CLI options (injected into commands)
  - Connection testing capability
- Dynamic discovery via `common.core.registry`

### Configuration

- XDG-compliant config path: `~/.local/share/fast-market/config/message-agent.yaml`
- Per-plugin configuration sections (e.g., `telegram:`)
- Interactive setup wizard via `setup` command

### User Interfaces

- **CLI**: Click-based with plugin option injection
- **Interactive Setup**: Guided configuration wizard

## 🔗 Component Dependencies

```
CLI (message_entry/__init__.py) → cli/main.py → Registry → Commands
                                                ↘ Plugins ↗
                                                      
Commands → Plugins (Telegram) → Telegram Bot API
```

## ✅ System-Wide Do's

### Architecture & Design
- **Use XDG paths**: Config in `~/.local/share/fast-market/config/`
- **Keep modules focused**: One responsibility per module
- **Use structlog for logging** with consistent field names
- **Return structured data** from commands, format via `helpers.out()`
- **Fail loudly**: Explicit exceptions with clear error messages

### Plugin Development
- Implement all `MessagePlugin` abstract methods
- Handle timeouts gracefully (return None or raise TimeoutError)
- Support Markdown formatting for messages
- Validate configuration in `__init__`

### Command Implementation
- Build plugin options dynamically from manifests (never hardcode plugin names)
- Use `ctx.obj` for global options (`--verbose`, `--format`)
- Delegate business logic to plugins (commands are thin orchestrators)
- Raise explicit exceptions with clear messages

## ❌ System-Wide Don'ts

### Never
- **Hardcode plugin names** — use manifests
- **Swallow exceptions** during plugin discovery/registration (FAIL LOUDLY)
- **Hardcode timeouts** — use config defaults with CLI override
- **Block indefinitely** without timeout option
- **Expose sensitive config** in logs

### Avoid
- **Business logic in commands** — keep them as orchestrators
- **Direct API calls** — always go through plugins
- **Hardcoded message formats** — allow Markdown

## 🛠️ Extension Points

### Add New Messaging Platform

1. Create `plugins/your_platform/` directory
2. Subclass `MessagePlugin` in `plugin.py`
3. Implement all abstract methods
4. Add `register.py` returning `PluginManifest`
5. Update CLI options in `register.py` as needed

### Add New Command

1. Create `commands/your_command/` with `__init__.py` and `register.py`
2. Implement `register(plugin_manifests) -> CommandManifest`
3. Define Click options
4. Registry auto-injects plugin options and registers command

## 📚 Related Documentation

- `common/` — Shared utilities (cli, core, registry)
- `GOLDEN_RULES.md` — Core principles: DRY, KISS, CODE IS LAW, FAIL LOUDLY

## 🔍 Key Design Decisions

### Why Blocking Wait for Ask?

The `ask` command blocks until a reply is received because:
- CLI tools often need synchronous confirmation before proceeding
- Simple error handling (timeout vs response)
- Matches expected shell scripting patterns

### Why Plugin-Based?

- Each messaging platform has unique APIs and auth flows
- Telegram as first implementation; easy to add Slack, Discord, etc.
- CLI commands remain platform-agnostic

### Why Telegram First?

- Bot API is simple and well-documented
- No OAuth complexity (just bot tokens)
- Widely accessible and reliable
- Good support for Markdown formatting

## Plugin Manifest Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Plugin identifier |
| `source_plugin_class` | type | `MessagePlugin` subclass |
| `cli_options` | dict | `{command_name: [click.Option, ...]}` |
