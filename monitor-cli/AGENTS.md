# monitor-agent

## 🎯 Purpose
A rule-based content monitoring agent that watches web sources (YouTube, RSS feeds) and executes shell commands when content matches user-defined conditions.

## 🏗️ Architecture Overview

```
monitor-agent/
├── core/                    # Core logic: models, rule engine, executor, storage
├── plugins/                 # Source plugins: youtube, rss, yt_search
├── commands/                # CLI commands: setup, run, logs, status, config, serve
├── api/                    # FastAPI server for web interface
├── ui/                     # HTML frontend pages
├── monitor_entry/          # CLI entry point
└── cli/                   # Internal CLI setup
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
- Placeholders: `$ITEM_TITLE`, `$ITEM_URL`, `$SOURCE_ID`, `$RULE_ID`, `$SOURCE_ORIGIN`, etc.
- Timeout protection (5 minutes)
- Output capture and logging
- **Error Handling**: Optional `on_error_action_ids` and `on_execution_action_ids` per rule
- **Global Fallbacks**: Optional `global_on_error_action_ids` and `global_on_execution_action_ids` in config

### Data Persistence
- SQLite database for sources, actions, rules, and trigger logs
- XDG-compliant paths:
  - Config: `~/.config/fast-market/monitor/config.yaml`
  - Data: `~/.local/share/fast-market/monitor/`
- Incremental tracking via `last_item_id`

### Source Cooldown
- Each source has a `slowdown` (in seconds) for cooldown between fetches
- Default: 900 seconds (15 minutes)
- Configured via `--slowdown` on source-add/source-edit

### What's New Mode (is_new)
- Each source has an `is_new` flag controlling trigger behavior:
  - `is_new=True` (default): Only trigger on new items since last check
  - `is_new=False`: Trigger on ALL items (like `--force` mode)
- Allows per-source control over whether to process only new items or all items

## 🔗 Component Dependencies

```
CLI (main.py) → Registry → Commands → Core → Storage
                      ↘ Plugins ↗

Commands:
  setup/  → Storage (CRUD for sources/actions/rules)
  run/    → RuleEngine + Executor + Storage
  logs/   → Storage (query trigger logs)
  status/ → Storage (statistics)
  config/ → Storage + YAML file sync
  serve/  → FastAPI server (web interface)

Core:
  models.py           → Dataclasses: Source, Action, Rule, ItemMetadata, TriggerLog, RuleEvaluationResult
  rule_engine.py      → evaluate_rule() recursive evaluator with mismatch logging
  config_schema.py    → Pydantic models for strict YAML validation with unknown field warnings
  executor.py         → Placeholder substitution: $RULE_ID, $SOURCE_ID, $SOURCE_ORIGIN
  rule_parser.py      → DSL string to internal format parser
  rule_formatter.py   → Internal format to DSL string formatter
  executor.py         → execute_action() with placeholders
  storage.py          → MonitorStorage with SQLite
  scheduler.py        → XDG path utilities
  time_scheduler.py   → Cron/interval scheduling logic
```

## ✅ System-Wide Do's

### Architecture & Design
- **Use XDG paths**: Config in `~/.config/fast-market/monitor/`, data in `~/.local/share/fast-market/monitor/`
- **Use dataclasses with slots** for memory efficiency
- **Return structured data** from commands, format via `out()`
- **Fail loudly**: Validate identifiers, log errors, don't swallow exceptions

### Rule Definition
- Use `all` for AND conditions, `any` for OR conditions
- Nest groups for complex logic (max 3 levels recommended)
- Test rules with `--force --dry-run` before production
- Use DSL syntax for human-readable conditions: `content_type == 'video' and duration > 600`
- Schedule rules with `--cron` or `--interval` options
- Use `$SOURCE_ID` in conditions to match specific sources
- Rule/engine provides detailed mismatch logging for debugging failed conditions

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
5. Add to `pyproject.toml` packages list

### Add Web Interface (serve command)
1. Create `api/server.py` with FastAPI app
2. Create `ui/*.html` frontend pages
3. Add API endpoints in server.py
4. Create `commands/serve/register.py` with uvicorn.run()
5. Include `api` and `ui` in package list

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

### Available Placeholders

#### Standard Placeholders (all actions)
| Placeholder | Description |
|-------------|-------------|
| `$ITEM_ID` | Item unique ID |
| `$ITEM_TITLE` | Item title |
| `$ITEM_URL` | Item URL |
| `$ITEM_CONTENT_TYPE` | video, short, article |
| `$ITEM_PUBLISHED` | ISO timestamp |
| `$SOURCE_ID` | Source UUID |
| `$SOURCE_PLUGIN` | youtube, rss |
| `$SOURCE_URL` | Channel/feed URL |
| `$SOURCE_DESC` | Source description |
| `$SOURCE_ORIGIN` | Channel ID or RSS URL |
| `$RULE_ID` | Rule identifier |
| `$EXTRA_<KEY>` | Any field from item.extra dict |

#### Error/Execution Context Placeholders (on_error / on_execution actions only)
| Placeholder | Description |
|-------------|-------------|
| `$RULE_ERROR` | Error message if main action failed (e.g., "Action 'notify' failed with exit code 127") |
| `$RULE_RESULT` | Exit code of main action (e.g., "exit=0") |
| `$RULE_MSG` | Formatted message: "Error: ..." or "Result: ..." |
| `$RULE_TIME` | ISO timestamp when the hook was triggered |

### Add on_error / on_execution Actions
1. Add `on_error_action_ids` and `on_execution_action_ids` to `Rule` model in `core/models.py`
2. Add corresponding columns to `rules` table in `core/storage.py`
3. Add CLI options in `commands/setup/register.py` for `--on-error-action-ids` and `--on-execution-action-ids`
4. Implement execution logic in `commands/run/register.py`
5. Add global config support via `load_tool_config()`

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
Path: `~/.config/fast-market/monitor/config.yaml`

Configuration uses strict YAML validation with Pydantic. Unknown fields generate warnings.

#### Global Action Hooks
```yaml
# Global actions triggered when any rule's action fails
global_on_error_action_ids:
  - error-handler-action

# Global actions triggered when any rule's action succeeds
global_on_execution_action_ids:
  - success-logger-action
```

These act as fallback hooks when a rule doesn't define its own `on_error_action_ids` or `on_execution_action_ids`.

### Identifier Conventions
- **Sources**: Use `id` for the source identifier, `origin` for the plugin-specific origin (e.g., channel ID for YouTube, URL for RSS)
- **Actions**: Use only `id` — no separate "name" field
- **Rules**: Use only `id` — no separate "name" field
- **Source in conditions**: Use `source_id == 'source-id'` to match items from specific sources
- **Source origin in conditions**: Use `source_origin == 'UCxxx'` to match by plugin-specific origin

### Database
Path: `~/.local/share/fast-market/monitor/monitor.db`

Tables:
- `sources` — Monitored sources with `origin`, `last_item_id`, `slowdown`, and `is_new` fields
- `actions` — Shell commands with last_run status
- `rules` — JSON conditions, action_ids, on_error_action_ids, on_execution_action_ids
- `trigger_logs` — Execution history for debugging
- `rule_mismatch_logs` — Detailed condition failure logs for debugging

## Usage Examples

```bash
# Add a YouTube channel source with metadata
monitor setup source-add --plugin youtube --identifier UC123456789 \
  --meta theme=technology --meta priority=high

# Add source with custom check interval (in seconds)
monitor setup source-add --plugin youtube --identifier UC123456789 \
  --slowdown 300

# Add source in "what's new" mode (default - only trigger on new items)
monitor setup source-add --plugin youtube --identifier UC123456789 --is-new

# Add source in "all items" mode (trigger on ALL items, like --force)
monitor setup source-add --plugin youtube --identifier UC123456789 --no-is-new

# Edit source to change check interval or is_new
monitor setup source-edit my-source --slowdown 600
monitor setup source-edit my-source --no-is-new

# Add an RSS feed source
monitor setup source-add --plugin rss --identifier https://example.com/feed.xml

# Add an action with custom ID (use --description for human-readable description)
monitor setup action-add --id telegram-notify \
  --command 'curl -X POST https://api.telegram.org/...'

# Replace an existing action
monitor setup action-add --replace-id telegram-notify --command 'new command'

# Add a rule with custom ID
monitor setup rule-add --id tech-shorts \
  --rule-file rule.yaml --action-ids telegram-notify

# Add inline rule with DSL (human-readable)
monitor setup rule-add --id "tech-videos" \
  --conditions "source_plugin == 'youtube' and content_type == 'video' and extra.duration > 600" \
  --action-ids <action-id>

# Add rule with DSL OR conditions
monitor setup rule-add --id "youtube-or-rss" \
  --conditions "source_plugin == 'youtube' or source_plugin == 'rss'" \
  --action-ids <action-id>

# Add rule with cron scheduling (hourly)
monitor setup rule-add --id "hourly-check" \
  --conditions "content_type == 'video'" \
  --cron "0 * * * *" \
  --action-ids <action-id>

# Add rule with interval scheduling (every 30 minutes)
monitor setup rule-add --id "frequent-check" \
  --conditions "source_metadata.priority == 'high'" \
  --interval "30m" \
  --action-ids <action-id>

# Add rule with on_error action (triggers when main action fails)
monitor setup rule-add --id "notify-with-error-handler" \
  --conditions "content_type == 'video'" \
  --action-ids telegram-notify \
  --on-error-action-ids error-alert

# Add rule with on_execution action (triggers after successful action)
monitor setup rule-add --id "notify-with-success-logger" \
  --conditions "content_type == 'video'" \
  --action-ids telegram-notify \
  --on-execution-action-ids log-success

# Add rule with both hooks
monitor setup rule-add --id "notify-with-hooks" \
  --conditions "content_type == 'video'" \
  --action-ids telegram-notify \
  --on-error-action-ids error-alert \
  --on-execution-action-ids log-success

# Edit rule to add/clear hooks
monitor setup rule-edit my-rule --on-error-action-ids new-error-handler
monitor setup rule-edit my-rule --clear-on-error-action-ids

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

# View mismatch logs (failed condition details)
monitor logs --mismatch --rule-id tech-shorts --format yaml

# Follow logs in real-time
monitor logs -f

# Follow logs with custom interval
monitor logs -f --interval 500ms

# Follow logs for specific source
monitor logs -f --source-id youtube_johannoriel

# Follow rule mismatch logs
monitor logs -f --mismatch

# Check status
monitor status --format json
monitor logs --since 1d --format json

# Check status
monitor status --format json

# Start web server for log viewing and status
monitor serve                    # Default port 8006
monitor serve -p 9000            # Custom port
```

## Web Interface

The `monitor serve` command starts a FastAPI web server with:

### Pages
- `/ui/logs` — Log viewer with filters and follow mode
- `/ui/status` — Dashboard showing sources, rules, actions, statistics

### API Endpoints
- `GET /api/logs` — Query trigger logs
  - Query params: `since`, `rule_id`, `source_id`, `action_id`, `limit`, `mismatch`
- `GET /api/status` — Get statistics and configured entities
- `GET /api/config` — Get current config file content
- `POST /api/config/sync` — Sync config from YAML file to database

Example:
```bash
# Query logs for specific rule
curl "http://localhost:8006/api/logs?rule_id=my-rule&since=1d&limit=50"

# Get status
curl http://localhost:8006/api/status
```
