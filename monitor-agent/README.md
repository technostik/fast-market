# monitor

Rule-based content monitoring agent that watches web sources and triggers actions.

## Features

- **Source Monitoring**: Watch YouTube channels and RSS feeds for new content
- **Rule Engine**: Define conditions with AND/OR logic and operators like `==`, `>`, `contains`, `matches`
- **Action Execution**: Run shell scripts with content placeholders
- **Incremental Tracking**: Avoid processing the same content twice
- **Force Mode**: Test rules without affecting tracking state
- **Cron Compatible**: Designed for minute-by-minute execution

## Installation

```bash
pip install -e ./monitor-agent
```

### Optional Dependencies

```bash
# YouTube API support (for @handle resolution)
pip install -e "./monitor-agent[youtube]"

# Development tools
pip install -e "./monitor-agent[dev]"
```

## Configuration

Monitor stores data in XDG-compliant directories:

- **Data**: `~/.local/share/fast-market/monitor/`
- **Database**: `~/.local/share/fast-market/monitor/monitor.db`

No YAML configuration file required — all settings are stored in the SQLite database.

## CLI Reference

### `monitor setup`

Configure sources, actions, and rules.

#### `monitor setup source-add`

Add a source to monitor.

```bash
# YouTube channel (by channel ID)
monitor setup source-add --plugin youtube --identifier UC123456789

# RSS feed
monitor setup source-add --plugin rss --identifier https://example.com/feed.xml

# With description and metadata
monitor setup source-add --plugin youtube --identifier UC123456789 \
  --description "Tech Reviews" \
  --meta theme=technology --meta priority=high
```

#### `monitor setup source-list`

List all configured sources.

```bash
monitor setup source-list --format json
```

#### `monitor setup source-delete`

Remove a source.

```bash
monitor setup source-delete --id <source-uuid>
```

#### `monitor setup action-add`

Add or replace an action (shell script) to execute.

```bash
# Simple notification
monitor setup action-add --name notify --command 'echo "New video: $ITEM_TITLE"'

# With custom ID (for easy referencing in rules)
monitor setup action-add --id telegram-notify \
  --name telegram \
  --command 'curl -s "https://api.telegram.org/bot$BOT_TOKEN/sendMessage?chat_id=$CHAT_ID&text=New: $ITEM_TITLE"' \
  --description "Send Telegram message"

# Replace an existing action
monitor setup action-add --replace-id telegram-notify --name telegram \
  --command 'curl -s "https://api.telegram.org/bot$TOKEN/sendMessage?..."'
```

**Available Placeholders:**

| Placeholder | Description |
|------------|-------------|
| `$ITEM_ID` | Item unique ID |
| `$ITEM_TITLE` | Item title |
| `$ITEM_URL` | Item URL |
| `$ITEM_CONTENT_TYPE` | video, short, article |
| `$ITEM_PUBLISHED` | ISO timestamp |
| `$SOURCE_ID` | Source UUID |
| `$SOURCE_PLUGIN` | youtube, rss |
| `$SOURCE_URL` | Channel ID or RSS URL |
| `$SOURCE_DESC` | Source description |
| `$RULE_NAME` | Matching rule name |
| `$EXTRA_*` | Any field from item metadata |

#### `monitor setup rule-add`

Add or replace a rule to match content.

```bash
# From file (YAML)
monitor setup rule-add --name "Long Videos" \
  --rule-file rule.yaml \
  --action-ids telegram-notify

# With custom ID
monitor setup rule-add --id tech-shorts --name "Tech Shorts" \
  --rule-file shorts.yaml \
  --action-ids telegram-notify

# Inline (JSON)
monitor setup rule-add --name "YouTube Shorts" \
  --conditions '{"all":[{"field":"content_type","operator":"==","value":"short"}]}' \
  --action-ids telegram-notify

# Replace an existing rule
monitor setup rule-add --replace-id tech-shorts --name "Tech Shorts" \
  --rule-file new-shorts.yaml --action-ids telegram-notify
```

**Rule Condition Format:**

```json
{
  "all": [...],  // AND: all conditions must match
  "any": [...]   // OR: any condition can match
}
```

**Available Rule Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id`, `title`, `url` | string | Item fields |
| `content_type` | string | video, short, article |
| `published_at` | datetime | Item publish time |
| `source_plugin` | string | youtube, rss |
| `source_identifier` | string | Channel ID or RSS URL |
| `source_description` | string | Source description |
| `source_metadata` | dict | Source metadata key-value pairs |
| `extra.*` | any | Plugin-specific fields (duration_seconds, categories, etc.) |

**Operators:**

| Operator | Description | Example |
|----------|-------------|---------|
| `==` | Equals | `{"field": "content_type", "operator": "==", "value": "video"}` |
| `!=` | Not equals | `{"field": "source_plugin", "operator": "!=", "value": "rss"}` |
| `>` | Greater than | `{"field": "extra.duration_seconds", "operator": ">", "value": 600}` |
| `<` | Less than | `{"field": "extra.word_count", "operator": "<", "value": 1000}` |
| `>=` | Greater or equal | `{"field": "extra.duration_seconds", "operator": ">=", "value": 600}` |
| `<=` | Less or equal | `{"field": "extra.views", "operator": "<=", "value": 100}` |
| `contains` | Contains value | `{"field": "extra.categories", "operator": "contains", "value": "tech"}` |
| `matches` | Regex match | `{"field": "title", "operator": "matches", "value": ".*AI.*"}` |

**Example Rule Files:**

```yaml
# long_videos.yaml - Videos longer than 10 minutes
all:
  - field: source_plugin
    operator: "=="
    value: youtube
  - field: content_type
    operator: "=="
    value: video
  - field: extra.duration_seconds
    operator: ">"
    value: 600
```

```yaml
# tech_articles.yaml - RSS articles with tech category
all:
  - field: source_plugin
    operator: "=="
    value: rss
  - any:
    - field: extra.categories
      operator: contains
      value: technology
    - field: extra.categories
      operator: contains
      value: programming
```

```yaml
# priority_shorts.yaml - Shorts from high-priority sources
all:
  - field: content_type
    operator: "=="
    value: short
  - field: source_metadata.priority
    operator: "=="
    value: high
```

#### `monitor setup rule-list`

List all configured rules.

```bash
monitor setup rule-list --format json
```

#### `monitor setup rule-delete`

Remove a rule.

```bash
monitor setup rule-delete --id <rule-uuid>
```

#### `monitor setup list`

Unified listing of sources, actions, and rules.

```bash
# List all (default)
monitor setup list

# List by type
monitor setup list --type sources
monitor setup list --type actions
monitor setup list --type rules

# JSON export
monitor setup list --type all --format json
```

#### `monitor setup rename`

Rename an entity ID (source, action, or rule) and update all references automatically.

```bash
# Rename an action and update all rules that reference it
monitor setup rename --from-id notify-v1 --to-id notify-v2
```

#### `monitor setup show`

Show configuration paths or export all config.

```bash
# Show paths
monitor setup show

# Export all config
monitor setup show --export yaml > backup.yaml
monitor setup show --export json > backup.json
```

---

### `monitor run`

Check sources and execute matching rules.

```bash
# Normal mode - only new items since last check
monitor run

# Force mode - re-process recent items (for testing)
monitor run --force

# Force with limit
monitor run --force --limit 10

# Dry run - evaluate rules without executing actions
monitor run --force --dry-run

# Specific source only
monitor run --source-id <uuid>

# Silent mode - suppress command output replay
monitor run --silent

# Cron mode - minimal output (implies silent)
*/1 * * * * monitor run --cron
```

**Options:**

| Option | Description |
|--------|-------------|
| `--cron` | Suppress output unless errors |
| `--dry-run` | Evaluate rules without executing actions |
| `--force` | Ignore last_fetched_at, process all available items |
| `--limit` | Max items per source (default: 50) |
| `--silent` | Suppress command output replay |
| `--source-id` | Run only for specific source |
| `--format` | Output format: `json`, `yaml`, or `text` |

**Output Example:**

```json
{
  "mode": "normal",
  "checked_sources": 2,
  "triggered_rules": 3,
  "limit_per_source": "unlimited",
  "triggers": [
    {
      "rule": "Long Videos",
      "rule_id": "abc123",
      "source": "UC123456789",
      "source_id": "def456",
      "source_metadata": {"theme": "tech", "priority": "high"},
      "item": {
        "id": "vid123",
        "title": "Introduction to Python",
        "url": "https://youtube.com/watch?v=vid123",
        "content_type": "video",
        "published": "2024-01-15T12:00:00+00:00",
        "extra": {"duration_seconds": 600}
      }
    }
  ]
}
```

---

### `monitor logs`

View or clean trigger history.

```bash
# Last 24 hours
monitor logs --since 1d

# Last hour
monitor logs --since 1h

# Specific rule
monitor logs --rule-id <uuid>

# Specific source
monitor logs --source-id <uuid>

# Filter by source metadata
monitor logs --meta-filter theme=technology

# JSON for scripting
monitor logs --since 7d --format json

# Find failed triggers
monitor logs --since 7d --format json | jq '.[] | select(.exit_code != 0)'

# Clean old logs
monitor logs --since 30d --clean

# Clean logs before a date
monitor logs --before 7d --clean
```

**Options:**

| Option | Description |
|--------|-------------|
| `--since` | Show/delete logs since: `1d`, `1h`, `30m`, or ISO date |
| `--before` | Delete logs before: `7d`, `30d`, or ISO date |
| `--clean` | Delete matching logs instead of showing |
| `--rule-id` | Filter by rule ID |
| `--source-id` | Filter by source ID |
| `--action-id` | Filter by action ID |
| `--meta-filter` | Filter by source metadata (key=value) |
| `--limit` | Max logs (default: 100) |
| `--format` | Output format: `json`, `yaml`, or `text` |

**Log Entry Fields:**

```json
{
  "id": "log-uuid",
  "rule_id": "rule-uuid",
  "source_id": "source-uuid",
  "source_metadata": {"theme": "tech", "priority": "high"},
  "action_id": "action-uuid",
  "item_id": "vid123",
  "item_title": "Video Title",
  "item_url": "https://youtube.com/...",
  "triggered_at": "2024-01-15T12:00:00",
  "exit_code": 0,
  "output": "Command output..."
}
```

---

### `monitor status`

Show monitor health and statistics.

```bash
monitor status

monitor status --format json
```

**Output Example:**

```json
{
  "statistics": {
    "sources_count": 2,
    "actions_count": 3,
    "rules_count": 2,
    "triggers_count": 47,
    "failed_triggers_count": 1,
    "last_trigger_at": "2024-01-15T14:30:00"
  },
  "sources": [...],
  "rules": [...],
  "actions": [...]
}
```

---

## Testing Your Rules

Use `--force --dry-run` to test rules without affecting tracking:

```bash
# Test all sources
monitor run --force --dry-run

# Test with limit
monitor run --force --limit 5 --dry-run

# Check specific source
monitor run --source-id <uuid> --force --dry-run
```

Force mode:
- Fetches items without respecting `last_item_id`
- Does NOT update tracking state
- Shows what WOULD trigger

## Cron Setup

Run every minute:

```bash
# Add to crontab
crontab -e

# Content
*/1 * * * * /path/to/monitor run --cron >> ~/.local/share/fast-market/monitor/cron.log 2>&1
```

## Architecture

```
monitor-agent/
├── core/              # Rule engine, executor, storage
├── plugins/           # youtube, rss source plugins
├── commands/          # CLI commands
└── monitor_entry/    # Entry point
```

**Flow:**

1. `run` command loads sources and rules from storage
2. Each source's plugin fetches items
3. Rule engine evaluates items against rules
4. Matching rules trigger action execution
5. Results logged to trigger_logs table

## Development

### Run Tests

```bash
cd monitor-agent
pytest tests/ -v
```

### Add New Source Plugin

1. Create `plugins/my_source/` directory
2. Implement `SourcePlugin` class
3. Add `register.py` returning `PluginManifest`

See `plugins/AGENTS.md` for details.

### Add New Command

1. Create `commands/my_command/` directory
2. Implement `register(plugin_manifests)` function
3. Return `CommandManifest`

See `commands/AGENTS.md` for details.

## Troubleshooting

### "No enabled sources found"

Run `monitor setup source-list` to check sources. Add sources with `monitor setup source-add`.

### "No enabled rules found"

Run `monitor setup rule-list` to check rules. Add rules with `monitor setup rule-add`.

### Rule not triggering

1. Use `--dry-run` to see what matches
2. Check rule conditions format
3. Verify action IDs are correct

### YouTube @handle not working

YouTube handle resolution requires API key. Use channel ID directly:

```bash
monitor setup source-add --plugin youtube --identifier UC...
```

## License

MIT
