# How to add a new plugin

## Architecture Overview

Plugins extend the corpus-agent to ingest content from different sources. Each plugin:
- Subclasses `SourcePlugin` from `plugins/base.py`
- Returns a `PluginManifest` from its `register()` function
- Provides `list_items()` for discovery and `fetch()` for content retrieval

## Required Files

Create `plugins/<name>/` with:
- `__init__.py` — empty
- `plugin.py` — your `SourcePlugin` subclass
- `register.py` — returns `PluginManifest`
- `AGENTS.md` — source documentation

## Step 1: Implement the SourcePlugin

```python
from plugins.base import SourcePlugin, ItemMeta
from core.models import Document

class MyPlugin(SourcePlugin):
    name = "myplugin"  # Must match manifest name

    def list_items(self, limit: int, known_id_dates: dict | None = None) -> list[ItemMeta]:
        # Return items that need indexing (new or modified)
        # known_id_dates: {source_id: indexed_updated_at} for existing docs
        ...

    def fetch(self, item_meta: ItemMeta) -> Document:
        # Return full Document with raw_text, title, etc.
        ...
```

## Step 2: Create the register() function

```python
from pathlib import Path
import click
from plugins.base import PluginManifest
from plugins.myplugin.plugin import MyPlugin

def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="myplugin",
        source_plugin_class=MyPlugin,
        cli_options={
            "search": [
                click.Option(["--my-filter"], type=int, default=None,
                             help="My plugin-specific filter."),
            ],
        },
        # api_router=my_router,  # optional FastAPI routes
        # frontend_js="...",     # optional JS for web UI
    )
```

## Step 3: Update pyproject.toml

Add `"plugins.<name>"` to `[tool.setuptools] packages`.

## Step 4: Write Tests

- Unit tests in `tests/test_<name>.py`
- Integration tests in `tests/test_cli.py`

## PluginManifest Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Must match `SourcePlugin.name` |
| `source_plugin_class` | type | The SourcePlugin subclass |
| `cli_options` | dict | `{command_name: [click.Option, ...]}` — use `"*"` for all commands |
| `api_router` | APIRouter? | Optional FastAPI routes |
| `frontend_js` | str? | Optional JS for web UI |

## Important Notes

1. **Do NOT declare `--source` option** — commands build it dynamically from registered plugins
2. **Use `known_id_dates`** in `list_items()` for efficient incremental sync:
   - YouTube: skip if source_id is present (ID-based dedup)
   - Obsidian: skip if source_id present AND mtime unchanged
3. The plugin is auto-discovered on startup — no changes to `cli/main.py` or `api/server.py`

## What Happens Automatically

- Plugin discovered by `core/registry.py`
- CLI options injected into relevant commands
- API router (if any) included in FastAPI app
- Frontend JS (if any) injected into web UI
