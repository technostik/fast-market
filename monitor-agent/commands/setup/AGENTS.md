# commands/setup/

## 🎯 Purpose
Configure sources, actions, and rules for the monitor agent. Provides CRUD operations for all configuration entities.

## 📋 Commands

### source-add
Add a new source to monitor.
```
monitor setup source-add --plugin youtube --identifier UC123456789
```

### source-list
List all configured sources.

### source-delete
Delete a source by ID.

### action-add
Add a new action (shell script).
```
monitor setup action-add --name notify --command 'echo "$ITEM_TITLE"'
```

### action-list
List all configured actions.

### action-delete
Delete an action by ID.

### rule-add
Add a new rule from file or inline conditions.
```
monitor setup rule-add --name "Long Videos" \
  --rule-file rule.yaml \
  --action-ids action1,action2

monitor setup rule-add --name "Shorts" \
  --conditions '{"all":[{"field":"content_type","operator":"==","value":"short"}]}' \
  --action-ids action1
```

### rule-list
List all configured rules.

### rule-delete
Delete a rule by ID.

### list
Unified listing of sources, actions, or rules.

## 🔗 Dependencies
- Imports from: `core.storage`, `core.models`, `click`, `yaml`
- Used by: CLI entry point

## ✅ Do's
- Validate identifiers before adding
- Support both YAML and JSON for rule files
- Use `click.Choice` for plugin selection
- Include helpful error messages

## ❌ Don'ts
- Don't add invalid identifiers — validate first
- Don't skip description fields — capture context
- Don't allow duplicate sources — check before adding

## 📚 Related Documentation
- See `AGENTS.md` (root) for system overview
- See `commands/AGENTS.md` for command patterns
- See `core/storage.py` for storage operations
