# monitor-agent

## 🎯 Purpose
A rule-based content monitoring agent that watches web sources (YouTube, RSS feeds) and executes shell commands when content matches user-defined conditions.

## 🏗️ Architecture Overview

```
monitor-agent/
├── core/                    # Core logic: models, rule engine, executor, storage
├── plugins/                 # Source plugins: youtube, rss
├── commands/                # CLI commands: setup, run, logs, status
├── monitor_entry/          # CLI entry point
└── cli/                    # Internal CLI setup
```

## 📋 Core System Responsibilities

### Rule-Based Monitoring
- Monitor YouTube channels via RSS feeds and RSS/Atom feeds
- Evaluate content against user-defined rules with AND/OR conditions
- Execute shell commands when rules match
- Track last seen items to avoid duplicate processing

### Rule Engine
- Recursive condition evaluator supporting nested AND/OR groups
- Operators: `==`, `!=`, `>`, `<`, `>=`, `<=`, `contains`, `matches`
- Dot notation for nested fields (`extra.duration_seconds`)
- Regex support via `matches` operator

### DSL Condition Syntax
- Human-readable condition strings (e.g., `content_type == 'video' and duration > 600`)
- Parse with `RuleParser` class
- Format back with `RuleFormatter` class
- Supports logical operators: `and`, `or`, parentheses grouping

### Time-Based Scheduling
- Schedule rules with cron expressions or intervals
- Cron: `--cron "0 * * * *"` for hourly runs
- Intervals: `--interval "30m"` for periodic runs
- Timezone support for scheduled rules
- `should_run_rule()` checks if rule should trigger

### Action Execution
- Shell script execution with placeholder substitution
- Placeholders: `$ITEM_TITLE`, `$ITEM_URL`, `$SOURCE_ID`, `$RULE_NAME`, etc.
- Timeout protection (5 minutes)
- Output capture and logging

### Data Persistence
- SQLite database for sources, actions, rules, and trigger logs
- XDG-compliant paths (`~/.local/share/fast-market/monitor/`)
- Incremental tracking via `last_item_id`

## 🔗 Component Dependencies

```
CLI (main.py) → Registry → Commands → Core → Storage
                      ↘ Plugins ↗

Commands:
  setup/  → Storage (CRUD for sources/actions/rules)
  run/    → RuleEngine + Executor + Storage
  logs/   → Storage (query trigger logs)
  status/ → Storage (statistics)

Core:
  models.py           → Dataclasses: Source, Action, Rule, ItemMetadata, TriggerLog
  rule_engine.py      → evaluate_rule() recursive evaluator
  rule_parser.py      → DSL string to internal format parser
  rule_formatter.py   → Internal format to DSL string formatter
  executor.py         → execute_action() with placeholders
  storage.py          → MonitorStorage with SQLite
  scheduler.py        → XDG path utilities
  time_scheduler.py   → Cron/interval scheduling logic
```

## ✅ System-Wide Do's

### Architecture & Design
- **Use XDG paths**: Data in `~/.local/share/fast-market/monitor/`
- **Use dataclasses with slots** for memory efficiency
- **Return structured data** from commands, format via `out()`
- **Fail loudly**: Validate identifiers, log errors, don't swallow exceptions

### Rule Definition
- Use `all` for AND conditions, `any` for OR conditions
- Nest groups for complex logic (max 3 levels recommended)
- Test rules with `--force --dry-run` before production
- Use DSL syntax for human-readable conditions: `content_type == 'video' and duration > 600`
- Schedule rules with `--cron` or `--interval` options

### Plugin Development
- Implement `fetch_new_items()` as async method
- Return items in chronological order (oldest first)
- Stop iteration when `last_item_id` is encountered
- Populate `extra` dict with plugin-specific metadata

### Command Implementation
- Use `plugin_manifests` to access plugin classes dynamically
- Accept `plugin_manifests` as parameter in `register()`
- Delegate business logic to core components
- Use `--cron` flag to suppress non-error output

## ❌ System-Wide Don'ts

### Never
- **Hardcode plugin names** — always use manifests
- **Skip identifier validation** — call `validate_identifier()` before adding sources
- **Swallow fetch exceptions** — log and continue to next source
- **Update last_item_id in force mode** — preserves original tracking
- **Use blocking I/O in plugins** — use `async/await` pattern

### Avoid
- **Complex nested rules** — prefer simpler, flatter conditions
- **Long-running actions** — default timeout is 5 minutes
- **Storing secrets in commands** — use environment variables
- **Mutating rule conditions** — treat rules as immutable in memory

## 🛠️ Extension Points

### Add New Source Plugin
1. Create `plugins/your_plugin/` directory
2. Subclass `SourcePlugin` in `plugins/your_plugin/plugin.py`
3. Implement `fetch_new_items()`, `validate_identifier()`, `get_identifier_display()`
4. Create `plugins/your_plugin/register.py` returning `PluginManifest`
5. Add `async` to `fetch_new_items()` for proper asyncio integration

### Add New Command
1. Create `commands/your_command/` with `__init__.py` and `register.py`
2. Implement `register(plugin_manifests) -> CommandManifest`
3. Define Click options in decorators
4. Use `out_formatted()` for consistent output

### Add New Rule Operator
1. Update `_evaluate_single_condition()` in `core/rule_engine.py`
2. Add operator case with clear error message for unknown operators
3. Add tests for the new operator

### Add DSL Parser Feature
1. Update `core/rule_parser.py` tokenizer or expression handlers
2. Update `core/rule_formatter.py` to handle new syntax
3. Add tests for parsing, formatting, and round-trip

### Add Schedule Type
1. Update `core/time_scheduler.py` with new trigger logic
2. Add validation function for the new schedule format
3. Update `should_run_rule()` to handle the new type

### Customize Placeholder Substitution
1. Modify `placeholders` dict in `core/executor.py`
2. Follow naming convention: uppercase with underscores
3. Update tests to cover new placeholders

## 📚 Related Documentation

- `GOLDEN_RULES.md` — Core principles: DRY, KISS, CODE IS LAW, FAIL LOUDLY
- `BUILD_NEW_AGENT_CLI.md` — General agent architecture guide
- `corpus-agent/AGENTS.md` — Similar indexing agent for reference

## 🔍 Key Design Decisions

### Why Rule-Based Instead of Event-Driven?
- Simpler mental model for users
- Easy to test with `--dry-run`
- Rules stored as JSON, no external DSL needed
- Recursive evaluation handles complex conditions

### Why SQLite Instead of PostgreSQL?
- Zero-config local storage
- Single file, easy backup
- Sufficient for single-user CLI tool
- No network dependencies

### Why Async Plugins?
- YouTube RSS can be slow
- RSS feeds may timeout
- Non-blocking allows parallel fetches
- Future: add concurrent source checking

### Why Placeholder-Based Actions?
- Shell scripts are universally understood
- No custom action syntax to learn
- Easy to integrate with existing tools
- Testable with `--dry-run`

## Configuration

### Config File (YAML)
Path: `~/.local/share/fast-market/config/monitor.yaml`

Currently empty — all configuration is via CLI and storage.

### Database
Path: `~/.local/share/fast-market/monitor/monitor.db`

Tables:
- `sources` — Monitored sources with last_item_id tracking
- `actions` — Shell commands with last_run status
- `rules` — JSON conditions and action references
- `trigger_logs` — Execution history for debugging

## Usage Examples

```bash
# Add a YouTube channel source with metadata
monitor setup source-add --plugin youtube --identifier UC123456789 \
  --meta theme=technology --meta priority=high

# Add an RSS feed source
monitor setup source-add --plugin rss --identifier https://example.com/feed.xml

# Add an action with custom ID
monitor setup action-add --id telegram-notify --name notify \
  --command 'curl -X POST https://api.telegram.org/...'

# Replace an existing action
monitor setup action-add --replace-id telegram-notify --command 'new command'

# Add a rule with custom ID
monitor setup rule-add --id tech-shorts --name "Tech Shorts" \
  --rule-file rule.yaml --action-ids telegram-notify

# Add inline rule with DSL (human-readable)
monitor setup rule-add --name "Tech Videos" \
  --conditions "source_plugin == 'youtube' and content_type == 'video' and extra.duration > 600" \
  --action-ids <action-id>

# Add rule with DSL OR conditions
monitor setup rule-add --name "YouTube or RSS" \
  --conditions "source_plugin == 'youtube' or source_plugin == 'rss'" \
  --action-ids <action-id>

# Add rule with cron scheduling (hourly)
monitor setup rule-add --name "Hourly Check" \
  --conditions "content_type == 'video'" \
  --cron "0 * * * *" \
  --action-ids <action-id>

# Add rule with interval scheduling (every 30 minutes)
monitor setup rule-add --name "Frequent Check" \
  --conditions "source_metadata.priority == 'high'" \
  --interval "30m" \
  --action-ids <action-id>

# Validate DSL condition without saving
monitor setup rule-validate "title matches '.*AI.*' and duration > 300"

# Show rule in human-readable format
monitor setup rule-show tech-shorts

# Run monitoring (normal mode)
monitor run

# Force mode (for testing)
monitor run --force --limit 10 --dry-run

# Run with YAML output
monitor run --force --limit 5 --format yaml

# Cron mode
*/1 * * * * monitor run --cron

# Export all config
monitor setup show --export yaml > backup.yaml

# View logs with filters
monitor logs --since 1d --action-id telegram-notify --format yaml

# Check status
monitor status --format json
monitor logs --since 1d --format json

# Check status
monitor status --format json
```
