# commands/run/

## 🎯 Purpose
Execute the monitoring loop: fetch items from sources, evaluate rules, and execute matching actions.

## 📋 Command Options

### --cron
Run in cron mode (minimal output, errors only).

### --source-id
Run only for a specific source.

### --dry-run
Evaluate rules without executing actions.

### --force
Ignore last_item_id, process all available items (for testing).

### --limit
Max items to process per source (default: 50).

### --format
Output format: `json` or `text`.

## Execution Flow

```
1. Load enabled sources from storage
2. Load enabled rules from storage
3. For each source:
   a. Create plugin instance
   b. Fetch items (respect last_item_id unless --force)
   c. For each item:
      - Evaluate each rule
      - If match, add to triggered list
   d. Update last_item_id (unless --force)
4. For each trigger:
   a. Execute each action
   b. Log trigger to storage
5. Output results (unless --cron)
```

## Normal vs Force Mode

| Scenario | Normal | Force |
|----------|--------|-------|
| Items newer than last_item_id | ✅ Processed | ✅ Processed |
| Items older than last_item_id | ❌ Skipped | ✅ Processed |
| Updates last_item_id | ✅ Yes | ❌ No |
| Use case | Production | Testing |

## Placeholders Available in Actions

| Placeholder | Description |
|-------------|-------------|
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
| `$EXTRA_*` | Any field from extra dict |

## Example Rule Conditions

```json
{
  "all": [
    {"field": "source_plugin", "operator": "==", "value": "youtube"},
    {"field": "content_type", "operator": "==", "value": "video"}
  ]
}
```

```json
{
  "any": [
    {"field": "extra.categories", "operator": "contains", "value": "technology"},
    {"field": "title", "operator": "matches", "value": ".*AI.*"}
  ]
}
```

## 🔗 Dependencies
- Imports from: `core.storage`, `core.rule_engine`, `core.executor`, `asyncio`
- Used by: CLI entry point

## ✅ Do's
- Use `asyncio.run()` for async plugin methods
- Handle exceptions per-source, continue with others
- Log all errors, don't fail silently
- Respect `--cron` for minimal output
- Don't update `last_item_id` in force mode

## ❌ Don'ts
- Don't execute actions in dry-run mode
- Don't update last_item_id when --force
- Don't skip sources that fail — log and continue
- Don't execute actions that timeout (5 min limit)

## 📚 Related Documentation
- See `AGENTS.md` (root) for system overview
- See `commands/AGENTS.md` for command patterns
- See `core/rule_engine.py` for condition syntax
- See `core/executor.py` for placeholder list
