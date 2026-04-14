# monitor

Rule-based content monitoring agent that watches web sources and triggers actions.

## Features

- **Source Monitoring**: Watch YouTube channels, RSS feeds, and search keywords for new content
- **Rule Engine**: Define conditions with AND/OR logic and operators like `==`, `>`, `contains`, `matches`
- **DSL Conditions**: Human-readable condition syntax (e.g., `content_type == 'video' and duration > 600`)
- **Time-Based Scheduling**: Schedule rules with cron expressions or intervals
- **Action Execution**: Run shell scripts with content placeholders
- **Error Handling**: Optional `on_error` and `on_execution` hooks per rule or globally
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

### Global Action Hooks (Optional)

Add to `~/.config/fast-market/monitor/config.yaml`:

```yaml
# Global actions triggered when any rule's action fails
global_on_error_action_ids:
  - error-handler-action

# Global actions triggered when any rule's action succeeds
global_on_execution_action_ids:
  - success-logger-action
```

These act as fallback hooks when a rule doesn't define its own `on_error_action_ids` or `on_execution_action_ids`.

## Source Cooldown

All sources have a built-in cooldown to prevent excessive fetching:

| Plugin | Default Interval | Configurable |
|--------|------------------|--------------|
| All plugins | `15m` | Yes |

Use `--slowdown` to control cooldown (supports `15m`, `1h`, `120s`, or plain seconds):

```bash
# More frequent checks (5 minutes)
monitor setup source-add --plugin youtube --identifier UC123456789 \
  --slowdown 5m

# Less frequent checks (1 hour)
monitor setup source-add --plugin rss --identifier https://example.com/feed.xml \
  --slowdown 1h

# Or use plain seconds
monitor setup source-add --plugin youtube --identifier UC123456789 \
  --slowdown 900
```

If no `slowdown` is set, all sources default to 15 minutes (900 seconds).

**Note:** For yt-search, you can also use `--meta slowdown=5m` (deprecated, use `--slowdown`).

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

# YouTube search by keywords (with config)
monitor setup source-add --plugin yt-search \
  --identifier "AI tutorial machine learning" \
  --meta theme=technology \
  --meta min_views=5000 \
  --meta max_results=30

# Channel list (monitor multiple YouTube channels)
monitor setup source-add --plugin channel_list \
  --identifier list \
  --slowdown 15m \
  --meta 'channels=[{"id":"UCX6OQ3DkcsbYNE6H8uQQuVA","title":"MrBeast"},{"id":"UCq-Fj5jknLsUf-MWSy4_brA","title":"T-Series"}]'

# Add source with custom slowdown (in seconds)
monitor setup source-add --plugin youtube --identifier UC123456789 \
  --slowdown 300

# Add source in "what's new" mode (default: only trigger on new items)
monitor setup source-add --plugin youtube --identifier UC123456789 --is-new

# Add source in "all items" mode (trigger on ALL items, like --force)
monitor setup source-add --plugin youtube --identifier UC123456789 --no-is-new
```

**Source Options:**

| Option | Description |
|--------|-------------|
| `--slowdown` | Cooldown interval in seconds between fetches (e.g., `300` for 5 minutes). Overrides metadata `slowdown`. |
| `--is-new` | If true (default), only trigger on new items since last check. If false, triggers on all items (like `--force`). |
| `--meta` | Metadata key=value pairs. For yt-search: `theme`, `min_views`, `max_results`; For channel_list: `channels`, `file`, `thematic` |

**yt-search Metadata Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `slowdown` | `15m` | Minimum time between searches (e.g., `15m`, `1h`, `30m`) - deprecated, use `--slowdown` |
| `min_views` | `1000` | Minimum view count to include (filters low-view videos) |
| `max_results` | `50` | Maximum videos to fetch per search |
| `theme` | - | User-defined theme (used in rules: `source_metadata.theme`) |

**channel_list Metadata Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `channels` | - | List of `{id: "UC...", title: "Channel Name"}` dicts (or use `file` + `thematic`) |
| `file` | - | Path to YAML channel list file (alternative to inline `channels`) |
| `thematic` | - | Thematic name to use from external file (required with `file`) |

**YouTube Search Advanced Syntax:**

YouTube search keywords support advanced operators:

```bash
# Exclude shorts
monitor setup source-add --plugin yt-search \
  --identifier "AI tutorial -shorts"

# OR operator (pipe)
monitor setup source-add --plugin yt-search \
  --identifier "cat video | dog video"

# Exact phrase
monitor setup source-add --plugin yt-search \
  --identifier "\"machine learning\" basics"

# Date range
monitor setup source-add --plugin yt-search \
  --identifier "AI tutorial 2024..2026"

# Exclude specific terms
monitor setup source-add --plugin yt-search \
  --identifier "python -beginner -tutorial"

# Combined advanced search
monitor setup source-add --plugin yt-search \
  --identifier "\"machine learning\" tutorial -shorts | \"deep learning\""
```

**Example: YouTube Search Rule**

```bash
# Add rule to trigger on new AI tutorial videos with 5000+ views
monitor setup rule-add --name "AI Tutorials" \
  --conditions "source_plugin == 'yt-search' and extra.views > 5000" \
  --action-ids notify

# Rule for popular shorts from tech search
monitor setup rule-add --name "Popular Tech Shorts" \
  --conditions "source_plugin == 'yt-search' and extra.is_short == True and extra.views > 10000" \
  --action-ids notify
```

**Example: Channel List Rules**

```bash
# Trigger on all channels in the channel_list source
monitor setup rule-add --name "Channel List Videos" \
  --conditions "source_plugin == 'channel_list' and content_type == 'video'" \
  --action-ids notify

# Trigger only on specific channel
monitor setup rule-add --name "MrBeast Videos" \
  --conditions "source_plugin == 'channel_list' and extra.channel_name == 'MrBeast'" \
  --action-ids notify

# Use channel-specific URL and description in actions
monitor setup action-add --id notify-channel \
  --command 'echo "New from $SOURCE_DESC: $ITEM_TITLE ($SOURCE_URL)"'
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

#### `monitor setup source-edit`

Edit an existing source interactively or with options.

```bash
# Interactive editor (opens $EDITOR)
monitor setup source-edit <source-id> -i

# Update description and metadata
monitor setup source-edit <source-id> \
  --description "Updated description" \
  --meta theme=tech --meta priority=high

# Disable a source
monitor setup source-edit <source-id> --disable

# Update slowdown (in seconds)
monitor setup source-edit <source-id> --slowdown 600

# Toggle "what's new" mode
monitor setup source-edit <source-id> --is-new      # Only new items trigger
monitor setup source-edit <source-id> --no-is-new   # All items trigger (like --force)

# Update channel_list channels
monitor setup source-edit <source-id> \
  --meta 'channels=[{"id":"UCnew1234567890abcdef","title":"New Channel"}]'
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

#### `monitor setup action-edit`

Edit an existing action interactively or with options.

```bash
# Interactive editor (opens $EDITOR)
monitor setup action-edit <action-id> -i

# Update command
monitor setup action-edit telegram-notify --command 'new curl command'

# Update name and description
monitor setup action-edit telegram-notify \
  --name "Telegram Alert" \
  --description "Production alert"
```

**Available Placeholders:**

| Placeholder | Description |
|------------|-------------|
| `$ITEM_ID` | Item unique ID |
| `$ITEM_TITLE` | Item title |
| `$ITEM_URL` | Item URL (video URL for YouTube) |
| `$ITEM_CONTENT_TYPE` | video, short, article |
| `$ITEM_PUBLISHED` | ISO timestamp |
| `$SOURCE_ID` | Source UUID |
| `$SOURCE_PLUGIN` | youtube, rss, channel_list |
| `$SOURCE_URL` | Channel/feed URL (e.g., `https://youtube.com/channel/UC...`) — **For channel_list: channel-specific URL** |
| `$SOURCE_DESC` | Source description — **For channel_list: "description (channel_name)"** |
| `$SOURCE_ORIGIN` | Channel ID or RSS URL |
| `$RULE_ID` | Rule identifier |
| `$EXTRA_*` | Any field from item metadata |

**Error/Execution Context Placeholders** (available in `on_error` and `on_execution` actions only):

| Placeholder | Description |
|------------|-------------|
| `$RULE_ERROR` | Error message if main action failed (e.g., "Action 'notify' failed with exit code 127") |
| `$RULE_RESULT` | Exit code of main action (e.g., "exit=0") |
| `$RULE_MSG` | Formatted message: "Error: ..." or "Result: ..." |
| `$RULE_TIME` | ISO timestamp when the hook was triggered | |

#### `monitor setup rule-add`

Add or replace a rule to match content.

```bash
# From file (YAML)
monitor setup rule-add --name "Long Videos" \
  --rule-file rule.yaml \
  --action-ids telegram-notify

# With DSL conditions (human-readable)
monitor setup rule-add --name "Tech Videos" \
  --conditions "source_plugin == 'youtube' and content_type == 'video' and extra.duration > 600" \
  --action-ids telegram-notify

# With custom ID
monitor setup rule-add --id tech-shorts --name "Tech Shorts" \
  --conditions "content_type == 'short'" \
  --action-ids telegram-notify

# Inline JSON (legacy format)
monitor setup rule-add --name "YouTube Shorts" \
  --conditions '{"all":[{"field":"content_type","operator":"==","value":"short"}]}' \
  --action-ids telegram-notify

# Replace an existing rule
monitor setup rule-add --replace-id tech-shorts --name "Tech Shorts" \
  --rule-file new-shorts.yaml --action-ids telegram-notify

# With on_error action (triggers when main action fails)
monitor setup rule-add --name "Notify with Error Handler" \
  --conditions "content_type == 'video'" \
  --action-ids telegram-notify \
  --on-error-action-ids error-alert

# With on_execution action (triggers after successful action)
monitor setup rule-add --name "Notify with Success Logger" \
  --conditions "content_type == 'video'" \
  --action-ids telegram-notify \
  --on-execution-action-ids log-success

# With both hooks
monitor setup rule-add --name "Full Hooks" \
  --conditions "content_type == 'video'" \
  --action-ids telegram-notify \
  --on-error-action-ids error-alert \
  --on-execution-action-ids log-success
```

### DSL Condition Syntax

Rules support a human-readable condition DSL in addition to JSON format:

```bash
# Simple equality
monitor setup rule-add --name "Videos" \
  --conditions "content_type == 'video'" \
  --action-ids notify

# Comparison operators
monitor setup rule-add --name "Long Videos" \
  --conditions "extra.duration > 600" \
  --action-ids notify

# Regex matching
monitor setup rule-add --name "AI Videos" \
  --conditions "title matches '.*AI.*'" \
  --action-ids notify

# AND conditions
monitor setup rule-add --name "Tech Videos" \
  --conditions "source_plugin == 'youtube' and extra.duration > 600" \
  --action-ids notify

# OR conditions
monitor setup rule-add --name "YouTube or RSS" \
  --conditions "source_plugin == 'youtube' or source_plugin == 'rss'" \
  --action-ids notify

# Nested grouping with parentheses
monitor setup rule-add --name "Tech Videos or Priority Shorts" \
  --conditions "(source_plugin == 'youtube' and content_type == 'video') or (source_metadata.priority == 'high' and content_type == 'short')" \
  --action-ids notify
```

**DSL Operators:**

| Operator | Description | Example |
|----------|-------------|---------|
| `==` | Equals | `content_type == 'video'` |
| `!=` | Not equals | `source_plugin != 'rss'` |
| `>` | Greater than | `extra.duration > 600` |
| `<` | Less than | `extra.views < 100` |
| `>=` | Greater or equal | `extra.rating >= 4.5` |
| `<=` | Less or equal | `extra.word_count <= 500` |
| `contains` | List contains | `extra.categories contains 'tech'` |
| `matches` | Regex match | `title matches '.*AI.*'` |

**Logical Operators:**

| Operator | Description |
|----------|-------------|
| `and` | All conditions must match |
| `or` | Any condition can match |
| `()` | Group conditions |

**Rule Condition Format (JSON):**

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
| `content_type` | string | short (< 60s), medium_video (1-10min), video (10-60min), long_video (> 1h), article |
| `published_at` | datetime | Item publish time |
| `source_plugin` | string | youtube, rss, yt-search |
| `source_identifier` | string | Channel ID or RSS URL |
| `source_description` | string | Source description |
| `source_metadata` | dict | Source metadata key-value pairs |
| `extra.*` | any | Plugin-specific fields (duration_seconds, categories, etc.) |

**YouTube Search (yt-search) Extra Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `extra.search_keywords` | string | Search keywords used |
| `extra.channel_id` | string | Video's source channel ID |
| `extra.channel_name` | string | Video's source channel name |
| `extra.duration_seconds` | int | Video duration in seconds |
| `extra.views` | int | Video view count |
| `extra.likes` | int | Like count |
| `extra.comments` | int | Comment count |
| `extra.is_short` | bool | True if video is a short (< 3 min) |
| `extra.tags` | list | Video tags |
| `extra.categories` | list | Video categories |

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

### Time-Based Rule Scheduling

Rules can be scheduled to run at specific times using cron expressions or intervals.

```bash
# Run hourly (at minute 0 of every hour)
monitor setup rule-add --name "Hourly Check" \
  --conditions "content_type == 'video'" \
  --cron "0 * * * *" \
  --action-ids notify

# Run every 30 minutes
monitor setup rule-add --name "Frequent Check" \
  --conditions "source_metadata.priority == 'high'" \
  --interval "30m" \
  --action-ids notify

# Run daily at 6 AM (UTC timezone)
monitor setup rule-add --name "Daily Digest" \
  --conditions "content_type == 'article'" \
  --cron "0 6 * * *" \
  --timezone "UTC" \
  --action-ids notify

# Run every 2 hours
monitor setup rule-add --name "Every 2 Hours" \
  --conditions "source_plugin == 'youtube'" \
  --interval "2h" \
  --action-ids notify
```

**Scheduling Options:**

| Option | Description | Example |
|--------|-------------|---------|
| `--cron` | Cron expression (minute hour day month weekday) | `0 * * * *` (hourly) |
| `--interval` | Time interval | `5m`, `1h`, `1d` |
| `--timezone` | Timezone for schedule (default: UTC) | `America/New_York` |

**Interval Format:**

| Unit | Description | Examples |
|------|-------------|----------|
| `s` | Seconds | `30s` |
| `m` | Minutes | `5m`, `30m` |
| `h` | Hours | `1h`, `2h`, `24h` |
| `d` | Days | `1d`, `7d` |

**Cron Format:**

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6, Sunday=0)
│ │ │ │ │
* * * * *
```

**Common Cron Examples:**

| Expression | Description |
|------------|-------------|
| `0 * * * *` | Every hour at minute 0 |
| `*/5 * * * *` | Every 5 minutes |
| `0 6 * * *` | Every day at 6 AM |
| `0 6 * * 1-5` | Weekdays at 6 AM |
| `30 18 * * *` | Every day at 6:30 PM |

**Rules without schedule:**

Rules without `--cron` or `--interval` will run every time `monitor run` is executed (default behavior).

### on_error and on_execution Actions

Rules can define optional hooks that trigger based on action results:

- **`on_error_action_ids`**: Triggered when a main action fails (non-zero exit code)
- **`on_execution_action_ids`**: Triggered after a main action succeeds

These hooks receive additional context placeholders:

```bash
# Example: notify with error handling
monitor setup action-add --id telegram-notify \
  --command 'curl -X POST ...'

monitor setup action-add --id error-alert \
  --command 'echo "ERROR on $RULE_ID: $RULE_ERROR" | mail admin@example.com'

monitor setup action-add --id log-success \
  --command 'echo "[$(date)] Rule $RULE_ID succeeded: $RULE_RESULT" >> /var/log/monitor.log'

monitor setup rule-add --name "Video Alert" \
  --conditions "content_type == 'video'" \
  --action-ids telegram-notify \
  --on-error-action-ids error-alert \
  --on-execution-action-ids log-success
```

**Execution Order:**

1. Main actions in `action_ids` execute
2. If any fails: per-rule `on_error_action_ids` runs → then global `global_on_error_action_ids`
3. If all succeed: per-rule `on_execution_action_ids` runs → then global `global_on_execution_action_ids`

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

#### `monitor setup rule-edit`

Edit an existing rule interactively or with options.

```bash
# Interactive editor (opens your $EDITOR with DSL format)
monitor setup rule-edit tech-shorts -i

# With specific editor
monitor setup rule-edit tech-shorts -i --editor vim

# Update name
monitor setup rule-edit tech-shorts --name "New Tech Shorts"

# Update conditions with DSL
monitor setup rule-edit tech-shorts --conditions "content_type == 'short' and extra.views > 1000"

# Update schedule
monitor setup rule-edit tech-shorts --cron "0 6 * * *"

# Remove schedule (run on every monitor run)
monitor setup rule-edit tech-shorts --no-schedule

# Update conditions from file
monitor setup rule-edit tech-shorts --rule-file new-conditions.yaml

# Update action references
monitor setup rule-edit tech-shorts --action-ids new-action-id

# Add on_error action
monitor setup rule-edit tech-shorts --on-error-action-ids error-handler

# Add on_execution action
monitor setup rule-edit tech-shorts --on-execution-action-ids success-logger

# Clear on_error actions
monitor setup rule-edit tech-shorts --clear-on-error-action-ids

# Clear on_execution actions
monitor setup rule-edit tech-shorts --clear-on-execution-action-ids

# Disable a rule
monitor setup rule-edit tech-shorts --disable
```

**Interactive Editor:**

Use `-i` flag to open your preferred editor (from `$EDITOR` or defaults to `nano`) with the rule in human-readable DSL format:

```yaml
name: Tech Shorts
description: My tech shorts rule
actions: [notify, backup]
timezone: UTC
conditions: |
  (source == 'youtube' and content_type == 'short') or
  (priority == 'high' and title matches '.*AI.*')
```

The editor shows helpful comments explaining the DSL syntax. After saving, the rule is validated and saved. If there are errors, you can re-edit.

#### `monitor setup rule-validate`

Validate a DSL condition string without saving.

```bash
# Validate a simple condition
monitor setup rule-validate "content_type == 'video'"

# Validate complex conditions
monitor setup rule-validate "(source_plugin == 'youtube' and content_type == 'video') or source_metadata.priority == 'high'"
```

#### `monitor setup rule-show`

Show a rule in human-readable format.

```bash
# Show as DSL (default)
monitor setup rule-show tech-shorts

# Show as JSON
monitor setup rule-show tech-shorts --format json

# Show as YAML
monitor setup rule-show tech-shorts --format yaml
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

#### `monitor setup config-show`

Show configuration paths or export all config.

```bash
# Show paths
monitor setup config-show

# Export all config
monitor setup show --export yaml > backup.yaml
monitor setup show --export json > backup.json
```

---

### `monitor run`

Check sources and execute matching rules.

```bash
# Normal mode - only new items since last check (respects source's is_new setting)
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

**What's New Mode (`is_new`):**

Each source has an `is_new` flag that controls whether triggers fire for new items only or all items:

| Source `is_new` | CLI `--force` | Behavior |
|-----------------|---------------|----------|
| `true` (default) | No | Only new items trigger |
| `true` | Yes | Only new items trigger (force bypasses cooldown) |
| `false` | No | All items trigger (like --force) |
| `false` | Yes | All items trigger |

Use `--is-new` or `--no-is-new` when adding/editing sources to control this behavior.

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

# Follow logs in real-time
monitor logs -f

# Follow with custom interval
monitor logs -f --interval 500ms

# Follow specific source
monitor logs -f --source-id <uuid>

# Follow rule mismatch logs
monitor logs -f --mismatch
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
| `-f`, `--follow` | Follow logs in real-time (like tail -f) |
| `--interval` | Polling interval for --follow (e.g., 1s, 500ms, 2s) |
| `--mismatch` | Show rule mismatch logs instead of trigger logs |

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
  "item_extra": {"duration_seconds": 600, "channel_name": "Tech Channel", "categories": ["tech"]},
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

How to have the correct venv and avoid concurrent calls : 
* * * * * /usr/bin/flock -n /tmp/monitor.lock bash -c 'source /path/to/venv/bin/activate && /path/to/venv/bin/monitor run --cron

## Architecture

```
monitor-agent/
├── core/              # Rule engine, executor, storage
├── plugins/           # youtube, rss, yt_search source plugins
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
