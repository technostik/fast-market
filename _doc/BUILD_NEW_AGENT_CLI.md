# How to Build a New Agent CLI (your-agent Architecture for fast-market project)

This document explains how to build a new CLI application with the same modular plugin/command architecture as existing xxx-agents in the fast-market project, using shared `common/` utilities.

## Architecture Overview

```
your-agent/
├── your_entry/           # CLI entry point (NOT cli/!)
│   └── __init__.py        # Imports main from cli.main
├── core/                  # Core logic (models, engine, config)
├── plugins/               # your engine plugins (flux2)
├── commands/              # CLI commands (generate, setup, serve)
├── api/                   # FastAPI server
└── common/                # Symlink to shared utilities
```

### Common Code (`common/`)

Shared utilities live at the workspace root and are imported by all tools:

| Path | Purpose |
|------|---------|
| `common/cli/base.py` | `create_cli_group()` — standard Click group factory |
| `common/cli/helpers.py` | `out()` — standard output formatting (JSON/text) |
| `common/core/config.py` | `load_tool_config()` — YAML config loading |
| `common/core/paths.py` | XDG-compliant paths (config, data, cache) |
| `common/core/registry.py` | Plugin/command discovery engine |
| `common/storage/base.py` | SQLAlchemy engine/session helpers |

### Core Concepts

1. **Plugin**: A data source that provides content (e.g., YouTube videos, Obsidian notes, GitHub issues)
2. **Command**: A CLI operation that works with plugins (e.g., `sync`, `search`, `list`)
3. **Registry**: Discovers plugins and commands at runtime via `register.py` files
4. **Manifest**: A dataclass that declares what a plugin/command contributes

---

## Step 1: Project Structure

Create your project with this minimal structure:

```
your-agent/
├── your_entry/          # CLI entry point (NOT cli/!)
│   └── __init__.py      # Imports and re-exports main from cli.main
├── core/
│   ├── __init__.py
│   ├── config.py            # Re-export from common (optional)
│   ├── registry.py          # Re-export from common (optional)
│   └── models.py            # Core data classes
├── plugins/
│   └── __init__.py
├── commands/
│   └── __init__.py
├── pyproject.toml
└── README.md
```

---

## Step 2: Core Components

### 2.1 Entry Point (your_entry/__init__.py)

This is the **required** entry point for your CLI. The `cli/main.py` is imported by this file, but the `[project.scripts]` in pyproject.toml **must** point here to avoid conflicts with other agents.

```python
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cli.main import main

__all__ = ["main"]
```

### 2.2 CLI Main (cli/main.py)

```python
from __future__ import annotations

import logging
from pathlib import Path

from common.cli.base import create_cli_group
from common.core.config import load_config
from common.core.registry import discover_commands, discover_plugins

main = create_cli_group("your-agent")
_TOOL_ROOT = Path(__file__).resolve().parents[1]


def _load() -> None:
    logging.basicConfig(level=logging.CRITICAL, force=True)
    config = load_config()
    plugin_manifests = discover_plugins(config, tool_root=_TOOL_ROOT)
    command_manifests = discover_commands(plugin_manifests, tool_root=_TOOL_ROOT)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)


_load()

if __name__ == "__main__":
    main()
```

### 2.3 Configuration (core/config.py)

Import from `common.core.config`:

```python
from __future__ import annotations

from common.core.config import load_config
```

XDG-compliant config path: `~/.local/share/fast-market/config/your-agent.yaml`

Use `load_tool_config("your-tool-name")` for tool-specific config loading.

### 2.4 Registry (core/registry.py)

Import from `common.core.registry`:

```python
from __future__ import annotations

from common.core.registry import discover_commands, discover_plugins, build_plugins
```

Functions from `common.core.registry`:

| Function | Purpose |
|----------|---------|
| `discover_plugins(config, tool_root=...)` | Scan `plugins/*/register.py` |
| `discover_commands(plugin_manifests, tool_root=...)` | Scan `commands/*/register.py` |
| `build_plugins(config, tool_root=...)` | Instantiate plugin classes from manifests |

### 2.5 Helper Utilities (commands/helpers.py)

```python
from __future__ import annotations

from common.cli.helpers import out
from common.core.registry import build_plugins


def build_engine(config: dict, tool_root: Path):
    """Construct the engine and plugins."""
    return build_plugins(config, tool_root=tool_root)
```

### 2.6 Storage (common/storage/base.py)

```python
from common.storage.base import create_sqlite_engine, session_scope
```

Functions from `common.storage.base`:

| Function | Purpose |
|----------|---------|
| `create_sqlite_engine(tool_name)` | Create persistent SQLite engine |
| `create_memory_engine()` | Create in-memory engine for testing |
| `session_scope(factory)` | Context manager for transactions |

---

## Step 3: Create a Plugin

### 3.1 Plugin Base (plugins/base.py)

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ItemMeta:
    """Metadata about an item to be fetched."""
    source_id: str
    updated_at: str | None = None
    metadata: dict | None = None


class SourcePlugin(ABC):
    """Abstract base class for source plugins."""
    name: str

    @abstractmethod
    def list_items(self, limit: int, known_id_dates: dict | None = None) -> list[ItemMeta]:
        """Return items that need indexing."""
        raise NotImplementedError

    @abstractmethod
    def fetch(self, item_meta: ItemMeta) -> "Document":
        """Fetch full document content."""
        raise NotImplementedError


@dataclass
class PluginManifest:
    """Everything a plugin contributes to the system."""
    name: str
    source_plugin_class: type
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
    frontend_js: str | None = None
```

### 3.2 Example Plugin (plugins/example/plugin.py)

```python
from plugins.base import SourcePlugin, ItemMeta
from core.models import Document


class ExamplePlugin(SourcePlugin):
    name = "example"

    def __init__(self, config: dict):
        self.config = config

    def list_items(self, limit: int, known_id_dates: dict | None = None) -> list[ItemMeta]:
        items = []
        return items

    def fetch(self, item_meta: ItemMeta) -> Document:
        return Document(
            source_plugin=self.name,
            source_id=item_meta.source_id,
            handle=f"{self.name}-{item_meta.source_id}",
            title="Document Title",
            raw_text="Full document content...",
            metadata=item_meta.metadata or {},
        )
```

### 3.3 Plugin Register (plugins/example/register.py)

```python
import click
from plugins.base import PluginManifest
from plugins.example.plugin import ExamplePlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="example",
        source_plugin_class=ExamplePlugin,
        cli_options={
            "search": [
                click.Option(
                    ["--my-filter"],
                    type=int,
                    default=None,
                    help="Example plugin filter option.",
                ),
            ],
        },
    )
```

### 3.4 Required Files

```
plugins/example/
├── __init__.py     # empty
├── plugin.py       # SourcePlugin subclass
└── register.py    # Returns PluginManifest
```

---

## Step 4: Create a Command

### 4.1 Command Base (commands/base.py)

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CommandManifest:
    """Everything a command contributes to the system."""
    name: str
    click_command: Any
    api_router: Any | None = None
    frontend_js: str | None = None
```

### 4.2 Example Command (commands/hello/register.py)

```python
import click
from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command("hello")
    @click.option("--name", default="World", help="Name to greet")
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def hello_cmd(ctx, name, source, fmt, **kwargs):
        plugins = build_engine(config, tool_root=_TOOL_ROOT)

        result = {
            "message": f"Hello, {name}!",
            "target": source,
            "plugins": list(plugins.keys()),
        }
        out(result, fmt)

    for pm in plugin_manifests.values():
        hello_cmd.params.extend(pm.cli_options.get("hello", []))

    return CommandManifest(
        name="hello",
        click_command=hello_cmd,
    )
```

### 4.3 Required Files

```
commands/hello/
├── __init__.py     # empty
└── register.py    # Returns CommandManifest
```

### 4.4 CLI Syntax Conventions

Follow these conventions for consistent CLI options across all commands:

#### Mandatory Short Forms

All options in the table below **must** have the specified short form in every command:

| Option | Short | Used By |
|--------|-------|---------|
| `--format` | `-F` | All data output commands (search, list, sync, etc.) |
| `--limit` | `-l` | Commands with pagination or item limits |
| `--output` | `-o` | File output commands |
| `--file` | `-f` | File input commands |

#### Option Guidelines

```python
# CORRECT: Always include short form for standard options
@click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.option("--limit", "-l", type=int, default=10)

# INCORRECT: Missing short form (violates standard)
@click.option("--format", "fmt", ...)
@click.option("--limit", type=int, ...)

# INCORRECT: Non-standard short form (conflicts with convention)
@click.option("--format", "-o", "fmt", ...)  # -o reserved for --output
```

#### Positional vs Options

| Type | Decorator | When to Use |
|------|-----------|-------------|
| **Positional** | `@click.argument` | Required primary inputs (query, handle, id) |
| **Option** | `@click.option` | Modifiers, format, limits, optional values |
| **Flag** | `@click.option(is_flag=True)` | Boolean toggles |

**Examples of correct usage:**
```python
@click.argument("query")                          # search query
@click.argument("handle")                         # document handle
@click.option("--source", type=click.Choice(...)) # filter (not positional)
@click.option("--limit", "-l", ...)               # pagination
```

#### Multiple Values

```python
# Use multiple=True for options that can be repeated
@click.option("--source", multiple=True, help="Filter by source (can repeat)")

# Usage: command --source a --source b --source c
```

#### Command vs Subcommand Groups

When a command has many related operations, prefer **subcommand groups** over boolean flags or pseudo-options:

| Pattern | Use When | Example |
|---------|----------|---------|
| **Single command with options** | One primary action, modifiers via flags | `alias`, `delete` |
| **Subcommand group** | Multiple related operations on the same noun | `setup providers list`, `task-prompts edit` |
| **Positional argument** | Command needs exactly one required identifier | `get <name>`, `delete <name>` |

**WRONG**: Boolean flags acting as subcommands:
```python
# BAD: Pseudo-options that should be subcommands
@click.option("--list-providers", is_flag=True)      # setup --list-providers
@click.option("--add-provider")                        # setup --add-provider <name>
@click.option("--show-prompt")                         # setup --show-prompt <name>
```

**CORRECT**: Subcommand groups:
```python
@click.group("setup")
def setup_group():
    """Setup management."""
    pass

@setup_group.command("providers-list")
def providers_list():
    """List providers."""

@setup_group.command("providers-add")
@click.argument("name")
def providers_add(name):
    """Add a provider."""

@setup_group.command("task-prompts-show")
@click.argument("name")
def task_prompts_show(name):
    """Show a task prompt."""
```

**Flat subcommand naming** (recommended for simplicity):
```
prompt setup providers-list
prompt setup providers-add <name>
prompt setup task-prompts-list
prompt setup task-prompts-show <name>
```

#### Real Options vs Pseudo-Options Checklist

Ask these questions for each potential option:

| Question | If Yes → | If No → |
|----------|----------|---------|
| Does the command NEED this to work? | **Positional argument** | Continue... |
| Does it select a noun (entity) to operate on? | **Subcommand**, not `--select-noun` | Continue... |
| Can it be combined with other options? | **Option** | Continue... |
| Is it a modifier toggle (yes/no)? | **Flag** (`is_flag=True`) | **Option with value** |

**Examples**:

| Feature Request | Correct Pattern | Reason |
|-----------------|------------------|--------|
| "list providers" | `providers-list` subcommand | Selects noun + verb |
| "add provider X" | `providers-add <name>` subcommand | Positional for required name |
| "show config" | `--show-config` option | Lightweight query, no noun |
| "show config for provider X" | `providers-show <name>` subcommand | Selects noun to operate on |
| "set timeout to N" | `task set-timeout <n>` subcommand | Verb on configuration noun |
| "quiet mode" | `--quiet` flag | Modifier toggle |

#### Option Short Forms

All standard options must have short forms. See [Mandatory Short Forms](#mandatory-short-forms).

#### Plugin-Aware Commands

Commands that work with plugins (sync, search, list, reindex, retry-failures) should build `--source` choices dynamically:

```python
def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command("my-command")
    @click.option("--source", type=click.Choice(source_choices), default="all")
    # ...
```

**Standard plugin-aware command structure:**
```python
@click.command("plugin-command")
@click.option("--source", type=click.Choice(source_choices), default="all")
@click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
```

---

## Step 5: Setup pyproject.toml

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "your-agent"
version = "0.1.0"
description = "Your agent description"
requires-python = ">=3.11"
dependencies = [
    "click>=8.1",
    "pyyaml>=6.0",
    "structlog>=24.2",
    "sqlalchemy>=2.0",
]

[project.optional-dependencies]
api = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
]

[project.scripts]
your-agent = "your_entry:main"

[tool.setuptools]
packages = [
    "cli",
    "core",
    "plugins",
    "plugins.example",
    "commands",
    "commands.hello",
    "your_entry",
]
```

---

## Step 6: Documentation

After creating new components, update the relevant `AGENTS.md` files following the pattern in `.doc/PROMPT_UPDATE_AGENTS_DOC.md`.

---

## Step 7: Testing

### Test Structure

```
your-agent/
├── tests/
│   ├── __init__.py
│   ├── conftest.py           # Shared fixtures
│   ├── test_plugin_*.py     # Plugin tests
│   ├── test_command_*.py    # Command tests
│   ├── test_storage.py      # Storage tests
│   └── data/                # Test fixtures
```

### conftest.py Pattern

```python
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def store() -> SQLiteStore:
    return SQLiteStore(":memory:")


@pytest.fixture
def mock_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch config and plugins for testing."""
    monkeypatch.chdir(tmp_path)
    # Add plugin mocks as needed
    return tmp_path
```

### Command Test Pattern

```python
import json
import importlib

from click.testing import CliRunner


def _main_with_reload():
    import cli.main as cli_mod
    importlib.reload(cli_mod)
    return cli_mod.main


def test_command_basic(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["command", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)
```

### Run Tests

```bash
# Run all tests
pytest your-agent/tests/

# Run with coverage
pytest --cov=your-agent tests/

# Run specific test file
pytest tests/test_command_name.py -v
```

---

## Step 8: Run Your Agent

```bash
# Install in development mode
pip install -e ".."

# Run CLI
your-agent --verbose hello --name "Your Name"

# List available commands
your-agent --help

# Add a new command
# Just create commands/newcmd/ with register.py
# No changes to cli/main.py needed!
```

---

## Step 9: How Discovery Works

1. **Startup**: `your_entry/__init__.py` imports `cli.main` which calls `_load()` on import
2. **Discover Plugins**: `discover_plugins()` scans `plugins/*/register.py`
3. **Discover Commands**: `discover_commands()` scans `commands/*/register.py`
4. **Inject Options**: Each command receives plugin-specific CLI options
5. **Register Commands**: All commands added to the Click group

---

## Step 10: Adding API Support (Optional)

Commands can contribute FastAPI routers:

```python
from fastapi import APIRouter
from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    def _build_router():
        router = APIRouter()

        @router.get("/hello")
        def hello_api(name: str = "World"):
            return {"message": f"Hello, {name}!"}

        return router

    return CommandManifest(
        name="hello",
        click_command=hello_cmd,
        api_router=_build_router(),
    )
```

Then in `api/server.py`:

```python
from fastapi import FastAPI
from common.core.registry import discover_commands

app = FastAPI()

for cmd in discover_commands().values():
    if cmd.api_router:
        app.include_router(cmd.api_router, prefix="/api")
```

---

## Step 11: Summary

### Shared Code (common/)

| Component | File | Purpose |
|-----------|------|---------|
| CLI Group | `common/cli/base.py` | `create_cli_group()` — Click group factory |
| Output | `common/cli/helpers.py` | `out()` — JSON/text formatting |
| Config | `common/core/config.py` | `load_tool_config()` — YAML loading |
| Paths | `common/core/paths.py` | XDG-compliant paths |
| Discovery | `common/core/registry.py` | `discover_plugins/commands()` |
| Storage | `common/storage/base.py` | SQLAlchemy engine/session helpers |

### Tool-Specific Code (your-agent/)

| Component | File | Purpose |
|-----------|------|---------|
| Entry Point | `your_entry/__init__.py` | CLI script entry (imports cli.main) |
| CLI Main | `cli/main.py` | Click group + plugin/command discovery |
| Plugin Base | `plugins/base.py` | `SourcePlugin` ABC + `PluginManifest` |
| Command Base | `commands/base.py` | `CommandManifest` |
| Plugin | `plugins/*/register.py` | Returns `PluginManifest` |
| Command | `commands/*/register.py` | Returns `CommandManifest` |

**Key Rules**:
- `[project.scripts]` **must** point to `your_entry:main` — NOT `cli.main:main`
- Never hardcode plugin names — use manifests
- Never modify cli/main.py when adding plugins/commands
- Use `**kwargs` to absorb plugin-injected options
- Build `--source` choices dynamically from manifests
- Import shared utilities from `common/`, not local copies
