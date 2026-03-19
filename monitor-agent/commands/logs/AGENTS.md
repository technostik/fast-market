# commands/logs/

## 🎯 Purpose
View trigger history and action execution results.

## 📋 Command Options

### --since
Show logs since time. Supports:
- Shorthand: `1d`, `1h`, `30m`
- ISO date: `2024-01-01` or `2024-01-01T00:00:00`

### --rule-id
Filter by rule ID.

### --source-id
Filter by source ID.

### --limit
Maximum number of logs to show (default: 100).

### --format
Output format: `json` or `text`.

## Log Entry Fields

```json
{
  "id": "log-uuid",
  "rule_id": "rule-uuid",
  "source_id": "source-uuid",
  "action_id": "action-uuid",
  "item_id": "video-id",
  "item_title": "Video Title",
  "item_url": "https://youtube.com/...",
  "triggered_at": "2024-01-01T12:00:00",
  "exit_code": 0,
  "output": "Command output..."
}
```

## Example Usage

```bash
# View last day's logs
monitor logs --since 1d

# View failed triggers
monitor logs --since 7d --format json | jq '.[] | select(.exit_code != 0)'

# View logs for specific rule
monitor logs --rule-id abc123

# View logs for specific source
monitor logs --source-id def456

# Limit to 10 most recent
monitor logs --limit 10
```

## 🔗 Dependencies
- Imports from: `core.storage`, `click`
- Used by: CLI entry point

## ✅ Do's
- Parse shorthand time formats correctly
- Truncate long outputs for display
- Support filtering by multiple criteria
- Show exit codes for debugging

## ❌ Don'ts
- Don't show all logs by default — use `--since` or `--limit`
- Don't expose full output if too long — truncate to ~500 chars
- Don't fail on missing optional filters

## 📚 Related Documentation
- See `AGENTS.md` (root) for system overview
- See `commands/AGENTS.md` for command patterns
- See `core/storage.py` for log storage
