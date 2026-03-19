# commands/status/

## 🎯 Purpose
Show monitor health, statistics, and configured entities.

## 📋 Output Sections

### Statistics
```json
{
  "sources_count": 3,
  "actions_count": 5,
  "rules_count": 2,
  "triggers_count": 42,
  "failed_triggers_count": 1,
  "last_trigger_at": "2024-01-01T12:00:00"
}
```

### Sources
List of configured sources with last check time.

### Rules
List of rules with action IDs and condition count.

### Actions
List of actions with last run time and exit code.

## Command Options

### --format
Output format: `json` or `text` (default).

## Example Usage

```bash
# Show status
monitor status

# JSON output for scripting
monitor status --format json

# Check if any triggers failed
monitor status --format json | jq '.statistics.failed_triggers_count'
```

## Health Indicators

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| failed_triggers_count | 0 | 1-5 | >5 |
| last_trigger_at | <1 hour | <1 day | >1 day |

## 🔗 Dependencies
- Imports from: `core.storage`, `click`
- Used by: CLI entry point

## ✅ Do's
- Show counts for all entity types
- Include last run times for actions
- Show condition complexity (count) for rules
- Include last check time for sources

## ❌ Don'ts
- Don't require network access for status
- Don't clear or modify data
- Don't fail on empty database

## 📚 Related Documentation
- See `AGENTS.md` (root) for system overview
- See `commands/AGENTS.md` for command patterns
- See `core/storage.py` for statistics queries
