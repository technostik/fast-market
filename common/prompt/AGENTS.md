# common/prompt Module

## Purpose
Unified prompt management service for all fast-market CLIs. Provides a centralized way to manage, override, and reset prompts that are used internally by various commands.

## Why
Previously, each CLI tool implemented its own prompt override mechanism. This module provides a clean, once-and-for-all solution where commands only need to declare their prompts in Click, and users can manage them via a consistent CLI interface.

## Storage

Prompts are stored in each tool's XDG config directory:
```
~/.config/fast-market/{tool}/prompts/{prompt_id}.yaml
```

**Prompt file format:**
```yaml
id: {prompt_id}
content: "user overridden prompt..."
```

Default prompts are provided by each CLI and are not stored in files - they come from code.

## API

### PromptManager

```python
from common.prompt import PromptManager

defaults = {"system": "You are helpful...", "summarize": "Summarize: {content}"}
manager = PromptManager("skill", defaults)
```

| Method | Description |
|--------|-------------|
| `create(prompt_id, content)` | Create new prompt override |
| `delete(prompt_id)` | Delete prompt override |
| `rename(old_id, new_id)` | Rename a prompt |
| `get(prompt_id)` | Get prompt content (returns default if not overridden) |
| `list()` | List all prompts: `[(prompt_id, is_overridden), ...]` |
| `set(prompt_id, content)` | Set/overwrite prompt content |
| `edit(prompt_id)` | Edit in default editor (nano) |
| `show()` | Show all prompts with content: `{id: (content, is_overridden)}` |
| `path(prompt_id=None)` | Get prompts dir path, or specific prompt path |
| `reset(prompt_id=None)` | Reset one or ALL prompts to defaults |

### register_commands

```python
import click
from common.prompt import register_commands

DEFAULT_PROMPTS = {
    "system": "You are a helpful assistant...",
    "summarize": "Summarize: {content}",
}

@click.group()
def cli():
    pass

register_commands(cli, "skill", DEFAULT_PROMPTS)
```

## CLI Commands

After integration, users get these subcommands under `{tool} prompt`:

| Command | Description |
|---------|-------------|
| `create <id> --content "..."` | Create new prompt override |
| `delete <id>` | Delete prompt override |
| `rename <old> <new>` | Rename a prompt |
| `get <id>` | Get prompt content |
| `list` | List all prompt IDs (overridden ones marked with `*`) |
| `set <id> --content "..."` | Set prompt content |
| `edit <id>` | Edit prompt in default editor |
| `show` | List all prompts with content |
| `path [id]` | Show prompts path |
| `reset [id]` | Reset one or ALL prompts to defaults |

All commands support autocomplete for prompt IDs.

## Do's
- Use `register_commands()` to integrate prompt management into your CLI
- Pass all default prompts as a dict to `register_commands()`
- Use descriptive prompt IDs (e.g., `system`, `summarize`, `analyze`)
- Call `manager.get(prompt_id)` to retrieve effective prompt (handles defaults automatically)

## Don'ts
- Don't store default prompts in files - they come from code
- Don't implement your own prompt override mechanism
- Don't hardcode prompt storage paths - use `PromptManager`
