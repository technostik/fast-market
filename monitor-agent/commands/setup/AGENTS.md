# commands/setup/

## 🎯 Purpose
Configure sources, actions, and rules for the monitor agent. Provides CRUD operations for all configuration entities.

## 📋 Commands

### source-add
Add a new source to monitor with optional metadata.
```
monitor setup source-add --plugin youtube --identifier UC123456789
monitor setup source-add --plugin youtube --identifier UC123456789 \
  --meta theme=technology --meta priority=high
```

### source-list
List all configured sources.

### source-delete
Delete a source by ID.

### action-add
Add or replace an action (shell script).
```
monitor setup action-add --name notify --command 'echo "$ITEM_TITLE"'
monitor setup action-add --id telegram-notify --name notify --command 'curl ...'
monitor setup action-add --replace-id telegram-notify --command 'new command'
```

### action-list
List all configured actions.

### action-delete
Delete an action by ID.

### rule-add
Add or replace a rule from file or inline conditions.
```
monitor setup rule-add --name "Long Videos" \
  --rule-file rule.yaml \
  --action-ids action1,action2

monitor setup rule-add --id tech-shorts --name "Tech Shorts" \
  --conditions '{"all":[{"field":"content_type","operator":"==","value":"short"}]}' \
  --action-ids notify

monitor setup rule-add --replace-id tech-shorts --rule-file new.yaml
```

### rule-list
List all configured rules.

### rule-delete
Delete a rule by ID.

### show
Show configuration file paths or export all config.
```
monitor setup show
monitor setup show --export yaml > backup.yaml
monitor setup show --export json > backup.json
```

### list
Unified listing of sources, actions, or rules (default: all).
```
monitor setup list
monitor setup list --type actions
monitor setup list --type all --format json
```

### rename
Rename an entity ID (source, action, or rule) and update all references.
```
monitor setup rename --from-id old-id --to-id new-id
monitor setup rename --from-id notify-v1 --to-id notify-v2
```

### source-edit
Edit an existing source.
```
monitor setup source-edit <source-id> --description "New description"
monitor setup source-edit <source-id> --meta theme=tech --meta priority=high
monitor setup source-edit <source-id> --disable
```

### action-edit
Edit an existing action.
```
monitor setup action-edit <action-id> --name "New name"
monitor setup action-edit <action-id> --command 'new command'
```

### rule-edit
Edit an existing rule interactively or with options.

**Interactive mode** (`-i` flag):
```
monitor setup rule-edit <rule-id> -i  # Opens $EDITOR with DSL format
monitor setup rule-edit <rule-id> -i --editor vim
```

**With options**:
```
monitor setup rule-edit <rule-id> --name "New name"
monitor setup rule-edit <rule-id> --conditions "content_type == 'video'"
monitor setup rule-edit <rule-id> --cron "0 6 * * *"
monitor setup rule-edit <rule-id> --rule-file new-conditions.yaml
monitor setup rule-edit <rule-id> --action-ids new-action-id
```

The interactive editor opens your `$EDITOR` (default: nano) with the rule in human-readable DSL format. Shows helpful comments and validates on save.

### config-show
Show configuration file paths or export all config.
```
monitor setup config-show
monitor setup config-show --export yaml > backup.yaml
monitor setup config-show --export json > backup.json
```

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
