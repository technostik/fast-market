# commands/

## 🎯 Purpose
Provides CLI commands for configuring and running the monitor agent. Each command is a self-contained module with its own registration logic.

## 🏗️ Essential Components
- `base.py` — CommandManifest dataclass
- `helpers.py` — Shared utilities: get_storage(), out_formatted()
- `setup/` — Configure sources, actions, and rules
- `run/` — Execute monitoring loop
- `logs/` — View trigger history
- `status/` — Show statistics and health

## 📋 Core Responsibilities
- Implement CLI commands using Click framework
- Accept plugin manifests for dynamic plugin access
- Format output consistently via `out_formatted()`
- Delegate business logic to core components

## 🔗 Dependencies & Integration
- Imports from: `core.storage`, `core.rule_engine`, `core.executor`, `click`
- Used by: `cli/main.py` (root Click group)
- External deps: `click`

## ✅ Do's
- Accept `plugin_manifests` as parameter in `register()`
- Use `get_storage()` for database access
- Use `out_formatted(data, fmt)` for output
- Return `CommandManifest` from `register()`
- Handle `--format json|text` for output formatting
- Handle `--cron` flag to suppress non-error output

### Setup Command
- Validate identifiers before adding sources
- Support both `--rule-file` and `--conditions` for rules
- Parse YAML/JSON for rule conditions

### Run Command
- Use `asyncio.run()` for async plugin methods
- Handle `--force` to ignore last_item_id
- Handle `--dry-run` to skip action execution
- Handle `--limit` to cap items per source
- Handle `--source-id` to target specific source

### Logs Command
- Parse `--since` with shorthand (1d, 1h, 30m) or ISO date
- Support `--rule-id` and `--source-id` filters
- Truncate long outputs in display

### Status Command
- Show counts: sources, actions, rules, triggers
- Show last trigger timestamp
- Show per-item details (last run, exit code)

## ❌ Don'ts
- Don't hardcode plugin names — use `plugin_manifests`
- Don't put business logic in commands — delegate to core
- Don't forget `--cron` output suppression
- Don't update storage in dry-run mode
- Don't modify `last_item_id` in force mode

## 🛠️ Extension Points

### Add New Command
1. Create `commands/your_command/` directory
2. Add empty `__init__.py`
3. Create `register.py` with `register(plugin_manifests) -> CommandManifest`
4. Define Click options in decorators
5. Implement command logic, delegating to core

### Example Command Structure
```python
def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("your-command")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def cmd(ctx, fmt):
        storage = get_storage()
        # ... logic ...
        out_formatted(result, fmt)

    return CommandManifest(name="your-command", click_command=cmd)
```

## 📚 Related Documentation
- See `AGENTS.md` (root) for system overview
- See `commands/base.py` for CommandManifest
- See `commands/helpers.py` for utilities
- See `commands/run/register.py` for monitoring logic
- See `BUILD_NEW_AGENT_CLI.md` for command patterns
