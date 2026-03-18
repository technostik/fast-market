# How to Build a New Agent CLI (corpus-agent Architecture)

This document explains how to build a new CLI application with the same modular plugin/command architecture as corpus-agent.

## Architecture Overview

```
your-agent/
├── cli/              # Entry point (main.py)
├── core/             # Shared infrastructure (config, registry, models)
├── plugins/         # Data source plugins (what to ingest)
├── commands/        # CLI commands (what to do)
├── storage/         # Data persistence
├── api/             # HTTP API (optional)
└── frontend/        # Web UI (optional)
```

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
├── cli/
│   ├── __init__.py
│   └── main.py              # CLI entry point
├── core/
│   ├── __init__.py
│   ├── config.py            # Configuration loading
│   ├── registry.py          # Plugin/command discovery
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

### 2.1 CLI Entry Point (cli/main.py)

```python
from __future__ import annotations

import logging
import click

from core.config import load_config
from core.registry import discover_plugins, discover_commands


@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False)
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


def _load() -> None:
    logging.basicConfig(level=logging.CRITICAL, force=True)
    config = load_config()
    plugin_manifests = discover_plugins(config)
    command_manifests = discover_commands(plugin_manifests)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)


_load()

if __name__ == "__main__":
    main()
```

### 2.2 Configuration (core/config.py)

```python
from __future__ import annotations

from pathlib import Path
import yaml


def load_config() -> dict:
    """Load configuration from XDG-compliant paths."""
    config_paths = [
        Path.home() / ".config" / "your-agent" / "config.yaml",
        Path.home() / ".your-agent" / "config.yaml",
    ]
    
    for path in config_paths:
        if path.exists():
            return yaml.safe_load(path.read_text()) or {}
    
    return {}


def get_config_path() -> Path:
    """Get the config file path, creating directory if needed."""
    config_dir = Path.home() / ".config" / "your-agent"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.yaml"
```

### 2.3 Registry (core/registry.py)

```python
from __future__ import annotations

import importlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def discover_plugins(config: dict) -> dict[str, "PluginManifest"]:
    """Scan plugins/ for subdirectories with register.py."""
    from plugins.base import PluginManifest
    
    plugins_dir = _ROOT / "plugins"
    manifests = {}
    
    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        mod_path = f"plugins.{entry.name}.register"
        try:
            mod = importlib.import_module(mod_path)
        except ModuleNotFoundError:
            continue
            
        if not hasattr(mod, "register"):
            raise RuntimeError(f"{mod_path} has no register() function")
            
        manifest = mod.register(config)
        if not isinstance(manifest, PluginManifest):
            raise TypeError(f"{mod_path}.register() must return PluginManifest")
            
        manifests[manifest.name] = manifest
    
    return manifests


def discover_commands(plugin_manifests: dict | None = None) -> dict[str, "CommandManifest"]:
    """Scan commands/ for subdirectories with register.py."""
    from commands.base import CommandManifest
    
    commands_dir = _ROOT / "commands"
    if not commands_dir.exists():
        return {}
    
    manifests = {}
    pm = plugin_manifests or {}
    
    for entry in sorted(commands_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        mod_path = f"commands.{entry.name}.register"
        try:
            mod = importlib.import_module(mod_path)
        except ModuleNotFoundError:
            continue
            
        if not hasattr(mod, "register"):
            raise RuntimeError(f"{mod_path} has no register() function")
            
        manifest = mod.register(pm)
        if not isinstance(manifest, CommandManifest):
            raise TypeError(f"{mod_path}.register() must return CommandManifest")
            
        manifests[manifest.name] = manifest
    
    return manifests


def build_plugins(config: dict) -> dict[str, object]:
    """Build plugin instances from manifests."""
    manifests = discover_plugins(config)
    return {name: m.source_plugin_class(config) for name, m in manifests.items()}
```

### 2.4 Data Models (core/models.py)

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Document:
    """A document to be indexed."""
    source_plugin: str
    source_id: str
    handle: str
    title: str
    raw_text: str
    metadata: dict = field(default_factory=dict)
    updated_at: datetime | None = None


@dataclass
class SearchResult:
    """A search result."""
    handle: str
    source_plugin: str
    source_id: str
    title: str
    excerpt: str
    score: float
    metadata: dict = field(default_factory=dict)
```

---

## Step 3: Create a Plugin

### 3.1 Plugin Base (plugins/base.py)

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ItemMeta:
    """Metadata about an item to be fetched."""
    source_id: str
    updated_at: datetime | None = None
    metadata: dict | None = None


class SourcePlugin(ABC):
    """Abstract base class for source plugins."""
    name: str

    @abstractmethod
    def list_items(self, limit: int, known_id_dates: dict | None = None) -> list[ItemMeta]:
        """Return items that need indexing."""
        raise NotImplementedError

    @abstractmethod
    def fetch(self, item_meta: ItemMeta) -> Document:
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
        # Return list of items to index
        # known_id_dates: {source_id: indexed_updated_at} for existing docs
        items = []
        # ... your logic here ...
        return items

    def fetch(self, item_meta: ItemMeta) -> Document:
        # Return full Document with raw_text, title, etc.
        return Document(
            source_plugin=self.name,
            source_id=item_meta.source_id,
            handle=f"{self.name}-{item_meta.source_id}",
            title="Document Title",
            raw_text="Full document content...",
            metadata=item_meta.metadata or {},
            updated_at=item_meta.updated_at,
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
    click_command: Any  # click.Command
    api_router: Any | None = None
    frontend_js: str | None = None
```

### 4.2 Helper Utilities (commands/helpers.py)

```python
from __future__ import annotations

import json
import click
import structlog

logger = structlog.get_logger(__name__)


def build_engine(verbose: bool):
    """Construct the engine, plugins, and store."""
    from core.config import load_config
    from core.registry import build_plugins
    
    config = load_config()
    plugins = build_plugins(config)
    return plugins


def out(data: object, fmt: str) -> None:
    """Output data in the specified format."""
    if fmt == "json":
        click.echo(json.dumps(data, ensure_ascii=False, default=str))
    else:
        click.echo(str(data))
```

### 4.3 Example Command (commands/hello/register.py)

```python
import click
from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:
    # Build dynamic source choices from plugins
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command("hello")
    @click.option("--name", default="World", help="Name to greet")
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def hello_cmd(ctx, name, source, fmt, **kwargs):
        plugins = build_engine(ctx.obj["verbose"])
        
        result = {
            "message": f"Hello, {name}!",
            "target": source,
            "plugins": list(plugins.keys()),
        }
        out(result, fmt)

    # Inject plugin-specific options for this command
    for pm in plugin_manifests.values():
        hello_cmd.params.extend(pm.cli_options.get("hello", []))

    return CommandManifest(
        name="hello",
        click_command=hello_cmd,
    )
```

### 4.4 Required Files

```
commands/hello/
├── __init__.py     # empty
└── register.py    # Returns CommandManifest
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
]

[project.optional-dependencies]
api = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
]

[project.scripts]
your-agent = "cli.main:main"

[tool.setuptools]
packages = [
    "cli",
    "core",
    "plugins",
    "plugins.example",
    "commands",
    "commands.hello",
]
```

---

## Step 6: Run Your Agent

```bash
# Install in development mode
pip install -e .

# Run CLI
your-agent --verbose hello --name "Your Name"

# List available commands
your-agent --help

# Add a new command
# Just create commands/newcmd/ with register.py
# No changes to cli/main.py needed!
```

---

## How Discovery Works

1. **Startup**: `cli/main.py` calls `_load()` on import
2. **Discover Plugins**: `discover_plugins()` scans `plugins/*/register.py`
3. **Discover Commands**: `discover_commands()` scans `commands/*/register.py`
4. **Inject Options**: Each command receives plugin-specific CLI options
5. **Register Commands**: All commands added to the Click group

---

## Adding API Support (Optional)

Commands can contribute FastAPI routers:

```python
from fastapi import APIRouter
from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    # ... CLI command definition ...
    
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
from core.registry import discover_commands

app = FastAPI()

# Include all command routers
for cmd in discover_commands().values():
    if cmd.api_router:
        app.include_router(cmd.api_router, prefix="/api")
```

---

## Summary

| Component | File | Purpose |
|-----------|------|---------|
| Entry Point | `cli/main.py` | Click group + discovery |
| Config | `core/config.py` | Load YAML config |
| Discovery | `core/registry.py` | Find plugins/commands |
| Plugin Base | `plugins/base.py` | `SourcePlugin` ABC + `PluginManifest` |
| Command Base | `commands/base.py` | `CommandManifest` |
| Plugin | `plugins/*/register.py` | Returns `PluginManifest` |
| Command | `commands/*/register.py` | Returns `CommandManifest` |

**Key Rules**:
- Never hardcode plugin names — use manifests
- Never modify cli/main.py when adding plugins/commands
- Use `**kwargs` to absorb plugin-injected options
- Build `--source` choices dynamically from manifests
