# How to add a new command

## Architecture Overview

Commands are CLI/API operations that work with plugins. Each command:
- Returns a `CommandManifest` from its `register()` function
- Receives `plugin_manifests` dict to access plugin capabilities
- Can contribute API routes and frontend JavaScript

## Required Files

Create `commands/<name>/` with:
- `__init__.py` — empty
- `register.py` — returns `CommandManifest`
- `AGENTS.md` — command documentation

## Step 1: Implement the register() function

```python
import click
from commands.base import CommandManifest
from commands.helpers import build_engine, out

def register(plugin_manifests: dict) -> CommandManifest:

    @click.command("myname")
    @click.option("--format", "fmt",
                  type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def my_cmd(ctx, fmt, **kwargs):
        engine, plugins, store = build_engine(ctx.obj["verbose"])
        # ... command logic ...
        out(result, fmt)

    # Inject plugin options for this command
    for pm in plugin_manifests.values():
        my_cmd.params.extend(pm.cli_options.get("myname", []))

    return CommandManifest(
        name="myname",
        click_command=my_cmd,
        # api_router=my_router,  # optional FastAPI routes
        # frontend_js="...",     # optional JS for web UI
    )
```

## Step 2: Update pyproject.toml

Add `"commands.<name>"` to `[tool.setuptools] packages`.

## Step 3: Write Tests

- CLI tests in `tests/test_cli.py`
- API tests in `tests/test_api.py`

## CommandManifest Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | CLI command name |
| `click_command` | click.Command | Decorated Click command |
| `api_router` | APIRouter? | Optional FastAPI routes |
| `frontend_js` | str? | Optional JS for web UI |

## Key Patterns

### Receiving Plugin Options
Use `**kwargs` to absorb injected options:
```python
def my_cmd(ctx, fmt, my_filter=None, **kwargs):
    # my_filter comes from plugin cli_options
```

### Building the --source Option
Commands that target specific plugins build this dynamically:
```python
@click.option("--source", type=click.Choice(list(plugin_manifests.keys()) + ["all"]))
```

### Using build_engine
```python
from commands.helpers import build_engine

engine, plugins, store = build_engine(verbose)
# engine: SyncEngine instance
# plugins: {name: SourcePlugin instance}
# store: SQLiteStore instance
```

## Important Notes

1. **Do NOT hardcode plugin names** — use `plugin_manifests.keys()`
2. **Do NOT redeclare global options** (--verbose, --format) — they're on the root group
3. Commands must be generic over plugins — iterate through `plugin_manifests`
4. The command is auto-discovered — no changes to `cli/main.py` or `api/server.py`

## What Happens Automatically

- Command discovered and added to CLI group
- Plugin-specific options injected
- API router (if any) included in FastAPI app
- Frontend JS (if any) injected into web UI
- Deleting the directory removes the command entirely
