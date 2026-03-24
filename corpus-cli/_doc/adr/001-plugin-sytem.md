# Phase 1 — Foundations: Data Structures + Registry

## Context

You are working on `corpus-agent`, a local content indexing tool.
The full codebase is available to you. This is the FIRST of 4 refactoring
phases. The goal of this phase is to lay the data structures and discovery
infrastructure that all subsequent phases will build on.

**After this phase the codebase must still work exactly as before.**
No existing behavior changes. You are only ADDING new files.

---

## What already exists (do not modify)

- `core/config.py`, `core/embedder.py`, `core/handle.py`, `core/models.py`,
  `core/sync_engine.py`
- `storage/sqlite_store.py`
- `plugins/base.py` (SourcePlugin ABC + ItemMeta — extend, do not rewrite)
- `plugins/obsidian/plugin.py`
- `plugins/youtube/plugin.py`
- `cli/main.py` (unchanged this phase)
- `api/server.py` (unchanged this phase)
- `structlog.py`, `yaml.py`, `setup_wizard.py`

---

## Files to create or modify in this phase

```
plugins/base.py              MODIFY — add PluginManifest dataclass
commands/__init__.py         CREATE (empty)
commands/base.py             CREATE — CommandManifest dataclass
commands/AGENTS.md           CREATE
core/registry.py             REWRITE — autodiscovery replacing manual dict
```

---

## Task 1: Extend plugins/base.py with PluginManifest

Add the following dataclass BELOW the existing `SourcePlugin` ABC.
Do not touch `ItemMeta` or `SourcePlugin`.

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class PluginManifest:
    """
    Everything a plugin contributes beyond its SourcePlugin logic.

    Fields:
        name:                 Must match SourcePlugin.name.
        source_plugin_class:  The SourcePlugin subclass (not an instance).
        cli_options:          {command_name: [click.Option, ...]}
                              Keys are CLI command names ("search", "sync", …).
                              Use "*" to inject into ALL commands.
        api_router:           Optional FastAPI APIRouter with plugin-specific endpoints.
        frontend_js:          Optional JS snippet injected into frontend pages.
    """
    name: str
    source_plugin_class: type
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
    frontend_js: str | None = None
```

---

## Task 2: Create commands/base.py with CommandManifest

```python
# commands/base.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandManifest:
    """
    Everything a command contributes to the system.

    Fields:
        name:          CLI name (e.g. "sync", "search").
        click_command: A fully-decorated @click.command (params may be extended
                       after creation by the registry injecting plugin options).
        api_router:    Optional FastAPI APIRouter with endpoints for this command.
        frontend_js:   Optional JS snippet injected into frontend pages.
    """
    name: str
    click_command: Any          # click.BaseCommand — avoid hard import at module level
    api_router: Any | None = None
    frontend_js: str | None = None
```

---

## Task 3: Rewrite core/registry.py

Replace the entire file. The new registry must:

1. Autodiscover plugin `register.py` files under `plugins/`.
2. Autodiscover command `register.py` files under `commands/` (directory may not
   exist yet — handle gracefully by returning empty dict).
3. Keep `build_plugins(config)` working identically to today (backward compat
   for `cli/main.py` and `api/server.py` which are unchanged this phase).

```python
# core/registry.py
from __future__ import annotations

import importlib
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_ROOT = Path(__file__).resolve().parent.parent


def discover_plugins(config: dict) -> dict[str, "PluginManifest"]:
    """
    Scan plugins/ for subdirectories containing register.py.
    Call register(config) -> PluginManifest for each.
    Fail loudly if register() is missing or raises.
    Skip __pycache__ and any dir starting with '_'.
    """
    from plugins.base import PluginManifest
    plugins_dir = _ROOT / "plugins"
    manifests: dict[str, PluginManifest] = {}

    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        mod_path = f"plugins.{entry.name}.register"
        try:
            mod = importlib.import_module(mod_path)
        except ModuleNotFoundError:
            # No register.py yet — skip silently during transition.
            # Once all plugins have register.py this should become a hard error.
            logger.info("plugin_no_register", plugin=entry.name)
            continue
        if not hasattr(mod, "register"):
            raise RuntimeError(
                f"FAIL LOUDLY: {mod_path} exists but has no register() function"
            )
        manifest: PluginManifest = mod.register(config)
        if not isinstance(manifest, PluginManifest):
            raise TypeError(
                f"FAIL LOUDLY: {mod_path}.register() must return PluginManifest, "
                f"got {type(manifest)}"
            )
        manifests[manifest.name] = manifest
        logger.info("plugin_registered", name=manifest.name)

    return manifests


def discover_commands(
    plugin_manifests: dict | None = None,
) -> dict[str, "CommandManifest"]:
    """
    Scan commands/ for subdirectories containing register.py.
    Call register(plugin_manifests) -> CommandManifest for each.
    Returns empty dict if commands/ directory does not exist yet.
    Fail loudly if register() exists but raises or returns wrong type.
    """
    from commands.base import CommandManifest
    commands_dir = _ROOT / "commands"
    if not commands_dir.exists():
        return {}

    manifests: dict[str, CommandManifest] = {}
    pm = plugin_manifests or {}

    for entry in sorted(commands_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        mod_path = f"commands.{entry.name}.register"
        try:
            mod = importlib.import_module(mod_path)
        except ModuleNotFoundError:
            logger.info("command_no_register", command=entry.name)
            continue
        if not hasattr(mod, "register"):
            raise RuntimeError(
                f"FAIL LOUDLY: {mod_path} exists but has no register() function"
            )
        manifest: CommandManifest = mod.register(pm)
        if not isinstance(manifest, CommandManifest):
            raise TypeError(
                f"FAIL LOUDLY: {mod_path}.register() must return CommandManifest, "
                f"got {type(manifest)}"
            )
        manifests[manifest.name] = manifest
        logger.info("command_registered", name=manifest.name)

    return manifests


def build_plugins(config: dict) -> dict[str, object]:
    """
    Backward-compatible builder used by cli/main.py and api/server.py today.
    Tries discover_plugins() first; falls back to direct instantiation if a
    plugin has no register.py yet (transition period only).
    """
    try:
        manifests = discover_plugins(config)
        if manifests:
            return {name: m.source_plugin_class(config) for name, m in manifests.items()}
    except Exception as exc:
        logger.error("discover_plugins_failed", error=str(exc))
        raise

    # Fallback: direct instantiation (remove once all register.py files exist)
    from plugins.obsidian.plugin import ObsidianPlugin
    from plugins.youtube.plugin import YouTubePlugin
    return {
        "obsidian": ObsidianPlugin(config),
        "youtube": YouTubePlugin(config),
    }
```

---

## Task 4: Create commands/AGENTS.md

```markdown
# commands/

Each subdirectory is a self-contained command module.

## Required structure per command directory

- `__init__.py` (empty)
- `register.py` — exports `register(plugin_manifests: dict) -> CommandManifest`
- `AGENTS.md` — describes what the command does and its extension points

## Rules

- Commands MUST NOT import plugin names directly (obsidian, youtube, etc.).
  They receive plugin_manifests and iterate generically.
- A command's base Click options are declared inside its own register.py.
  Plugin-specific options are injected by the registry at load time via
  `command.params.extend(plugin_manifest.cli_options.get(cmd_name, []))`.
- The --source option for commands that target a specific plugin (sync, reindex)
  is built dynamically: `list(plugin_manifests.keys()) + ["all"]`.
  No command hardcodes ["obsidian", "youtube"].
- Global options (--verbose, --format) live on the root Click group.
  Commands read them via ctx.obj — they must NOT re-declare them.
- Deleting a command directory removes it from CLI and API entirely.
  No other file needs to change.
- Use structlog, raise explicit exceptions. Follow KISS and DRY.
```

---

## Task 5: Create commands/__init__.py

Empty file.

---

## Verification

After completing this phase, run the existing test suite:

```bash
cd corpus-agent
python -m pytest tests/ -x -q
```

All existing tests must pass. Additionally verify manually:

```python
# Quick smoke test — run this in the corpus-agent directory
from core.config import load_config
from core.registry import discover_plugins, discover_commands, build_plugins

config = load_config()

# Should return empty dict (no register.py files yet)
plugins = discover_plugins(config)
print("plugins via discover:", plugins)  # expect {}

# Should return empty dict (commands/ dir is empty)
commands = discover_commands()
print("commands via discover:", commands)  # expect {}

# Must still work exactly as before
built = build_plugins(config)
print("build_plugins fallback:", list(built.keys()))  # expect ['obsidian', 'youtube']
```

---

## What this phase does NOT do

- Does not create any `register.py` file in any plugin or command directory.
- Does not change `cli/main.py` or `api/server.py`.
- Does not create any command subdirectories.

The codebase is fully functional and identical in behavior to before.


# Phase 2 — Plugin Registers

## Context

You are working on `corpus-agent`. This is phase 2 of 4.

Phase 1 added:
- `PluginManifest` dataclass in `plugins/base.py`
- `CommandManifest` dataclass in `commands/base.py`
- `discover_plugins()` / `discover_commands()` / `build_plugins()` in `core/registry.py`
- Empty `commands/` directory with `AGENTS.md`

**After this phase the codebase must still work exactly as before.**
No CLI or API behavior changes. You are only adding `register.py` files
inside the existing plugin directories.

---

## What already exists (do not modify)

- `plugins/obsidian/plugin.py`
- `plugins/youtube/plugin.py`
- `plugins/base.py` (with PluginManifest added in phase 1)
- `core/registry.py` (with discover_plugins)
- `cli/main.py` — unchanged
- `api/server.py` — unchanged

---

## Files to create in this phase

```
plugins/obsidian/register.py     CREATE
plugins/youtube/register.py      CREATE
plugins/obsidian/AGENTS.md       UPDATE — add register.py section
plugins/youtube/AGENTS.md        UPDATE — add register.py section
```

---

## Key design rule: --source is NOT declared by plugins

The `--source` CLI option (choosing which plugin to target) is built
dynamically by COMMANDS from `plugin_manifests.keys()`. Plugins must NOT
declare a `--source` option. Each plugin only declares options that are
specific to it and not shared with other plugins.

---

## Task 1: Create plugins/obsidian/register.py

Obsidian-specific CLI options across commands:

- `search` command: `--since` (YYYY-MM-DD), `--until` (YYYY-MM-DD),
  `--min-size` (int, chars), `--max-size` (int, chars)
- No obsidian-specific sync options (sync is source-agnostic beyond --source)
- No obsidian-specific API endpoints needed (generic `/items?source=obsidian` suffices)
- No frontend_js needed for now

```python
# plugins/obsidian/register.py
from __future__ import annotations

import click

from plugins.base import PluginManifest
from plugins.obsidian.plugin import ObsidianPlugin


def register(config: dict) -> PluginManifest:
    """Declare everything the obsidian plugin contributes to the system."""
    return PluginManifest(
        name="obsidian",
        source_plugin_class=ObsidianPlugin,
        cli_options={
            "search": [
                click.Option(
                    ["--since"],
                    default=None,
                    help="Filter by date: only notes updated on or after YYYY-MM-DD.",
                ),
                click.Option(
                    ["--until"],
                    default=None,
                    help="Filter by date: only notes updated on or before YYYY-MM-DD.",
                ),
                click.Option(
                    ["--min-size"],
                    type=int,
                    default=None,
                    help="Minimum note size in characters.",
                ),
                click.Option(
                    ["--max-size"],
                    type=int,
                    default=None,
                    help="Maximum note size in characters.",
                ),
            ],
        },
        api_router=None,
        frontend_js=None,
    )
```

---

## Task 2: Create plugins/youtube/register.py

YouTube-specific CLI options across commands:

- `search` command: `--type` (short/long), `--min-duration` (int seconds),
  `--max-duration` (int seconds), `--privacy-status`
- No youtube-specific sync options (sync is source-agnostic beyond --source)
- No youtube-specific API endpoints needed

```python
# plugins/youtube/register.py
from __future__ import annotations

import click

from plugins.base import PluginManifest
from plugins.youtube.plugin import YouTubePlugin


def register(config: dict) -> PluginManifest:
    """Declare everything the youtube plugin contributes to the system."""
    return PluginManifest(
        name="youtube",
        source_plugin_class=YouTubePlugin,
        cli_options={
            "search": [
                click.Option(
                    ["--type", "video_type"],
                    type=click.Choice(["short", "long"]),
                    default=None,
                    help="Filter by video type (short ≤60s, long >60s).",
                ),
                click.Option(
                    ["--min-duration"],
                    type=int,
                    default=None,
                    help="Minimum video duration in seconds.",
                ),
                click.Option(
                    ["--max-duration"],
                    type=int,
                    default=None,
                    help="Maximum video duration in seconds.",
                ),
                click.Option(
                    ["--privacy-status"],
                    type=click.Choice(["public", "unlisted", "private", "unknown"]),
                    default=None,
                    help="Filter by YouTube privacy status.",
                ),
            ],
        },
        api_router=None,
        frontend_js=None,
    )
```

---

## Task 3: Update plugins/obsidian/AGENTS.md

Append a new section at the end of the existing file:

```markdown
## register.py

`register(config) -> PluginManifest` declares what this plugin contributes
to the CLI, API, and frontend. Current contributions:

- `cli_options["search"]`: --since, --until, --min-size, --max-size
- No plugin-specific API routes (generic /items?source=obsidian is sufficient)
- No frontend JS fragment

To add a new CLI option to a command, add a click.Option to the relevant
cli_options list. The registry injects it automatically. Do not touch main.py.
```

---

## Task 4: Update plugins/youtube/AGENTS.md

Append a new section at the end of the existing file:

```markdown
## register.py

`register(config) -> PluginManifest` declares what this plugin contributes
to the CLI, API, and frontend. Current contributions:

- `cli_options["search"]`: --type, --min-duration, --max-duration, --privacy-status
- No plugin-specific API routes
- No frontend JS fragment

To add a new CLI option to a command, add a click.Option to the relevant
cli_options list. The registry injects it automatically. Do not touch main.py.

## Note on --source option

The --source CLI option (choosing which plugin to target) is built by COMMANDS
from plugin_manifests.keys(). This plugin must NOT declare --source.
```

---

## Verification

After completing this phase, run the existing tests:

```bash
cd corpus-agent
python -m pytest tests/ -x -q
```

All existing tests must pass.

Then run this smoke test to verify discovery works:

```python
from core.config import load_config
from core.registry import discover_plugins, build_plugins

config = load_config()

# Must now return both plugins via their register.py files
manifests = discover_plugins(config)
print("discovered:", list(manifests.keys()))
# expect: ['obsidian', 'youtube']

# Verify obsidian manifest
ob = manifests["obsidian"]
print("obsidian class:", ob.source_plugin_class.__name__)  # ObsidianPlugin
print("obsidian search options:", [o.name for o in ob.cli_options.get("search", [])])
# expect: ['since', 'until', 'min_size', 'max_size']

# Verify youtube manifest
yt = manifests["youtube"]
print("youtube class:", yt.source_plugin_class.__name__)   # YouTubePlugin
print("youtube search options:", [o.name for o in yt.cli_options.get("search", [])])
# expect: ['video_type', 'min_duration', 'max_duration', 'privacy_status']

# build_plugins must still work (used by unchanged cli/main.py)
plugins = build_plugins(config)
print("build_plugins:", list(plugins.keys()))
# expect: ['obsidian', 'youtube']
```

---

## What this phase does NOT do

- Does not create any command `register.py` files.
- Does not change `cli/main.py`, `api/server.py`, or any frontend file.
- The CLI and API behave exactly as before.

# Phase 3 — Command Registers

## Context

You are working on `corpus-agent`. This is phase 3 of 4.

Phases 1 and 2 added:
- `PluginManifest` / `CommandManifest` dataclasses
- `discover_plugins()` / `discover_commands()` in `core/registry.py`
- `plugins/obsidian/register.py` and `plugins/youtube/register.py`

This phase creates every `commands/<n>/register.py` file. Each one encapsulates
the logic currently hardcoded in `cli/main.py` and `api/server.py`.

**`cli/main.py` and `api/server.py` are still unchanged at the end of this phase.**
The commands directory and its files are scaffolded and tested in isolation,
but not yet wired into the actual entry points. That is phase 4.

---

## What already exists (do not modify)

- `core/sync_engine.py`, `core/embedder.py`, `core/config.py`
- `storage/sqlite_store.py` (SearchFilters is here)
- `plugins/obsidian/plugin.py`, `plugins/youtube/plugin.py`
- `plugins/obsidian/register.py`, `plugins/youtube/register.py`
- `core/registry.py`
- `cli/main.py` — still the monolith, unchanged this phase
- `api/server.py` — unchanged this phase

Read `cli/main.py` carefully before starting — you are extracting its logic,
not reinventing it.

---

## Files to create in this phase

```
commands/sync/       __init__.py, register.py, AGENTS.md
commands/search/     __init__.py, register.py, AGENTS.md
commands/get/        __init__.py, register.py, AGENTS.md
commands/delete/     __init__.py, register.py, AGENTS.md
commands/status/     __init__.py, register.py, AGENTS.md
commands/reindex/    __init__.py, register.py, AGENTS.md
commands/serve/      __init__.py, register.py, AGENTS.md
commands/setup/      __init__.py, register.py, AGENTS.md
```

---

## Shared helpers to put in commands/helpers.py

Before writing individual commands, create a shared helpers module to avoid
repeating the build/logging setup in every command.

```python
# commands/helpers.py
from __future__ import annotations

import json
import sys

import click
import structlog

logger = structlog.get_logger(__name__)


def build_engine(verbose: bool):
    """Construct the SyncEngine, plugins, and store from config. Mirrors _build() in cli/main.py."""
    import logging
    from core.config import load_config
    from core.embedder import Embedder
    from core.registry import build_plugins
    from core.sync_engine import SyncEngine
    from storage.sqlite_store import SQLiteStore

    _configure_logging(verbose)
    config = load_config()
    store = SQLiteStore(config.get("db_path", ":memory:"))
    embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
    engine = SyncEngine(store, embedder)
    plugins = build_plugins(config)
    return engine, plugins, store


def out(data: object, fmt: str) -> None:
    if fmt == "json":
        click.echo(json.dumps(data, ensure_ascii=False, default=str))
    else:
        _print_text(data)


def _print_text(data: object) -> None:
    if isinstance(data, list):
        for item in data:
            _print_text(item)
            click.echo("")
    elif isinstance(data, dict):
        for k, v in data.items():
            if k == "raw_text":
                continue
            click.echo(f"  {k}: {v}")
    else:
        click.echo(str(data))


def fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


# Copy _configure_logging and _make_silent_tqdm verbatim from cli/main.py
# (do not import from cli/main.py — commands must not depend on the CLI layer)
_NOISY_LOGGERS = [
    "core", "storage", "plugins", "sentence_transformers",
    "transformers", "huggingface_hub", "torch", "filelock",
    "urllib3", "httpx",
]

def _configure_logging(verbose: bool) -> None:
    import logging
    level = logging.INFO if verbose else logging.CRITICAL
    logging.basicConfig(level=level, stream=sys.stderr,
                        format="%(asctime)s [%(levelname)-8s] %(name)s %(message)s",
                        force=True)
    logging.root.setLevel(level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)
    if not verbose:
        try:
            from tqdm import tqdm
            tqdm.__init__ = _make_silent_tqdm(tqdm.__init__)
        except ImportError:
            pass
        try:
            import transformers
            transformers.logging.set_verbosity_error()
        except (ImportError, AttributeError):
            pass
        try:
            import sentence_transformers.logging as st_log
            st_log.set_verbosity_error()
        except (ImportError, AttributeError):
            pass


def _make_silent_tqdm(original_init):
    def patched(self, *args, **kwargs):
        kwargs["disable"] = True
        original_init(self, *args, **kwargs)
    return patched
```

---

## How plugin options are injected into a command

Every command that accepts plugin-contributed options must:

1. Declare its own base options with `@click.command` + `@click.option` decorators.
2. After building the command object, extend its params:

```python
def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("search")
    @click.argument("query")
    @click.option("--mode", ...)
    @click.pass_context
    def search_cmd(ctx, query, mode, **kwargs):
        # kwargs contains all plugin-injected options
        ...

    # Inject plugin-specific options BEFORE returning
    for pm in plugin_manifests.values():
        search_cmd.params.extend(pm.cli_options.get("search", []))

    return CommandManifest(name="search", click_command=search_cmd, ...)
```

The command callback uses `**kwargs` to absorb all injected params.
It then passes them to `SearchFilters(...)` by name. Since `SearchFilters.__init__`
already accepts all current filter params by keyword, this works without
changes to SearchFilters.

**Important**: To build `SearchFilters` from kwargs without knowing which keys
came from which plugin, filter the kwargs dict to only the keys SearchFilters
accepts:

```python
from storage.sqlite_store import SearchFilters
import inspect

_SF_PARAMS = set(inspect.signature(SearchFilters.__init__).parameters) - {"self"}

def make_filters(**kwargs) -> SearchFilters:
    return SearchFilters(**{k: v for k, v in kwargs.items() if k in _SF_PARAMS})
```

Put `make_filters` in `commands/helpers.py`.

---

## How --source is built dynamically

For `sync` and `reindex` commands, the `--source` option's choices must come
from the registered plugin names, not be hardcoded. Build it inside `register()`:

```python
def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command("sync")
    @click.option("--source", type=click.Choice(source_choices), default="all")
    ...
```

If `plugin_manifests` is empty (e.g. during testing before plugins are set up),
the choices list will be `["all"]` — graceful degradation.

---

## commands/sync/register.py

Extract from `cli/main.py`'s `sync` command. Key behaviors to preserve:
- `--source all` iterates all registered plugins
- `--clean` calls `store.delete_all()` before syncing
- `--limit` has plugin-specific defaults: 5 for youtube, 10 for others
  (this logic should move here, keyed on plugin name)
- Default limit fallback: 10

The API router for sync: POST `/sync` (currently in `api/server.py`).
Extract it here as an `APIRouter`.

```python
# commands/sync/register.py
from __future__ import annotations
import click
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from commands.base import CommandManifest
from commands.helpers import build_engine, out


_DEFAULT_LIMITS = {"youtube": 5}
_FALLBACK_LIMIT = 10


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command("sync")
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option("--mode", type=click.Choice(["new", "backfill"]), default="new")
    @click.option("--limit", type=int, default=None)
    @click.option("--clean", is_flag=True, default=False)
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def sync_cmd(ctx, source, mode, limit, clean, fmt, **kwargs):
        engine, plugins, store = build_engine(ctx.obj["verbose"])
        if clean:
            store.delete_all()
        targets = list(plugins.keys()) if source == "all" else [source]
        results = []
        for name in targets:
            effective_limit = limit if limit is not None else _DEFAULT_LIMITS.get(name, _FALLBACK_LIMIT)
            result = engine.sync(plugins[name], mode=mode, limit=effective_limit)
            results.append({
                "source": result.source,
                "indexed": result.indexed,
                "skipped": result.skipped,
                "failures": len(result.failures),
                "errors": [{"source_id": f.source_id, "error": f.error} for f in result.failures],
            })
        out(results, fmt)

    return CommandManifest(
        name="sync",
        click_command=sync_cmd,
        api_router=_build_router(source_choices),
    )


def _build_router(source_choices: list[str]) -> APIRouter:
    router = APIRouter()

    class SyncRequest(BaseModel):
        source: str
        mode: str = "new"
        limit: int = 10

    @router.post("/sync")
    def sync(req: SyncRequest):
        from core.config import load_config
        from core.embedder import Embedder
        from core.registry import build_plugins
        from core.sync_engine import SyncEngine
        from storage.sqlite_store import SQLiteStore
        if req.source not in source_choices:
            raise HTTPException(status_code=400, detail="Unknown source")
        config = load_config()
        store = SQLiteStore(config.get("db_path", ":memory:"))
        embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
        engine = SyncEngine(store, embedder)
        plugins = build_plugins(config)
        result = engine.sync(plugins[req.source], mode=req.mode, limit=req.limit)
        return {"source": result.source, "indexed": result.indexed,
                "skipped": result.skipped, "failures": len(result.failures)}

    return router
```

**Note on the API router store/engine construction**: The API routers currently
create their own store/engine inline (matching the current pattern in
`api/server.py` which has module-level singletons). For now, replicate the
current pattern. A future phase can introduce proper dependency injection.

---

## commands/search/register.py

Extract from `cli/main.py`'s `search` command and `api/server.py`'s `/search`.

Key behaviors to preserve:
- `--mode semantic` (default) and `--mode keyword`
- Text output: `[handle] title  duration=Xm00s  privacy=public`
- JSON output: full result objects with score
- Plugin options (`--min-duration`, `--since`, etc.) are injected, not hardcoded

```python
# commands/search/register.py
from __future__ import annotations
import inspect
import click
from fastapi import APIRouter, HTTPException
from commands.base import CommandManifest
from commands.helpers import build_engine, out, fmt_duration, make_filters


def register(plugin_manifests: dict) -> CommandManifest:

    @click.command("search")
    @click.argument("query")
    @click.option("--mode", type=click.Choice(["semantic", "keyword"]), default="semantic")
    @click.option("--limit", type=int, default=5)
    @click.option("--source", type=click.Choice(list(plugin_manifests.keys())), default=None)
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def search_cmd(ctx, query, mode, limit, source, fmt, **kwargs):
        engine, _, store = build_engine(ctx.obj["verbose"])
        filters = make_filters(source=source, **kwargs)
        if mode == "keyword":
            results = store.keyword_search(query, limit, filters)
        else:
            vector = engine.embedder.embed_texts([query])[0][1]
            results = store.semantic_search(vector, limit, filters)

        if fmt == "json":
            out([{
                "handle": r.handle,
                "source_plugin": r.source_plugin,
                "source_id": r.source_id,
                "title": r.title,
                "score": round(r.score, 4),
                "duration_seconds": r.duration_seconds,
                "privacy_status": r.privacy_status,
                "excerpt": r.excerpt,
            } for r in results], fmt)
        else:
            if not results:
                click.echo("no results")
                return
            for r in results:
                dur = f"  duration={fmt_duration(r.duration_seconds)}" if r.duration_seconds else ""
                priv = f"  privacy={r.privacy_status}" if r.privacy_status else ""
                click.echo(f"[{r.handle}] {r.title}{dur}{priv}")
                click.echo(f"  score={round(r.score, 4)}  source={r.source_plugin}")
                click.echo(f"  {r.excerpt[:120]}")

    # Inject plugin-contributed search options
    for pm in plugin_manifests.values():
        search_cmd.params.extend(pm.cli_options.get("search", []))

    return CommandManifest(
        name="search",
        click_command=search_cmd,
        api_router=_build_router(),
    )


def _build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/search")
    def search(
        q: str,
        mode: str = "semantic",
        limit: int = 5,
        source: str | None = None,
        video_type: str | None = None,
        min_duration: int | None = None,
        max_duration: int | None = None,
        since: str | None = None,
        until: str | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
        privacy_status: str | None = None,
    ):
        from core.config import load_config
        from core.embedder import Embedder
        from core.registry import build_plugins
        from core.sync_engine import SyncEngine
        from storage.sqlite_store import SQLiteStore, SearchFilters
        config = load_config()
        store = SQLiteStore(config.get("db_path", ":memory:"))
        embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
        filters = SearchFilters(source=source, video_type=video_type,
            min_duration=min_duration, max_duration=max_duration,
            since=since, until=until, min_size=min_size, max_size=max_size,
            privacy_status=privacy_status)
        if mode == "keyword":
            results = store.keyword_search(q, limit, filters)
        elif mode == "semantic":
            vector = embedder.embed_texts([q])[0][1]
            results = store.semantic_search(vector, limit, filters)
        else:
            raise HTTPException(status_code=400, detail="Invalid mode")
        return [{"handle": r.handle, "source_plugin": r.source_plugin,
                 "source_id": r.source_id, "title": r.title,
                 "excerpt": r.excerpt, "score": r.score,
                 "duration_seconds": r.duration_seconds} for r in results]

    return router
```

---

## commands/get/register.py

Extract `get` command and `GET /document/{source_plugin}/{source_id}` +
`GET /handle/{handle}` routes.

```python
# commands/get/register.py
from __future__ import annotations
import sys
import click
from fastapi import APIRouter, HTTPException
from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:

    @click.command("get")
    @click.argument("handle")
    @click.option("--what", type=click.Choice(["meta", "content", "all"]), default="meta")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def get_cmd(ctx, handle, what, fmt, **kwargs):
        _, _, store = build_engine(ctx.obj["verbose"])
        doc = store.get_document_by_handle(handle)
        if not doc:
            click.echo(f"not found: {handle}", err=True)
            sys.exit(1)
        if what == "content":
            click.echo(doc["raw_text"])
            return
        if what == "meta":
            out({k: v for k, v in doc.items() if k != "raw_text"}, fmt)
            return
        if fmt == "json":
            out(doc, fmt)
        else:
            for k, v in doc.items():
                if k == "raw_text":
                    click.echo(f"\n--- content ({len(v)} chars) ---\n")
                    click.echo(v)
                else:
                    click.echo(f"  {k}: {v}")

    return CommandManifest(
        name="get",
        click_command=get_cmd,
        api_router=_build_router(),
    )


def _build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/document/{source_plugin}/{source_id:path}")
    def get_document(source_plugin: str, source_id: str):
        from core.config import load_config
        from storage.sqlite_store import SQLiteStore
        config = load_config()
        store = SQLiteStore(config.get("db_path", ":memory:"))
        doc = store.get_document(source_plugin, source_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc

    @router.get("/handle/{handle}")
    def get_by_handle(handle: str):
        from core.config import load_config
        from storage.sqlite_store import SQLiteStore
        config = load_config()
        store = SQLiteStore(config.get("db_path", ":memory:"))
        doc = store.get_document_by_handle(handle)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc

    return router
```

---

## commands/delete/register.py

Extract `delete` command and `DELETE /document/{source_plugin}/{source_id}`.

```python
# commands/delete/register.py
from __future__ import annotations
import sys
import click
from fastapi import APIRouter, HTTPException
from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:

    @click.command("delete")
    @click.argument("handle")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def delete_cmd(ctx, handle, fmt, **kwargs):
        _, _, store = build_engine(ctx.obj["verbose"])
        deleted = store.delete_document_by_handle(handle)
        if deleted:
            out({"deleted": True, "handle": handle}, fmt)
        else:
            click.echo(f"not found: {handle}", err=True)
            sys.exit(1)

    return CommandManifest(
        name="delete",
        click_command=delete_cmd,
        api_router=_build_router(),
    )


def _build_router() -> APIRouter:
    router = APIRouter()

    @router.delete("/document/{source_plugin}/{source_id:path}")
    def delete_document(source_plugin: str, source_id: str):
        from core.config import load_config
        from storage.sqlite_store import SQLiteStore
        config = load_config()
        store = SQLiteStore(config.get("db_path", ":memory:"))
        deleted = store.delete_document(source_plugin, source_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"deleted": True, "source_plugin": source_plugin, "source_id": source_id}

    return router
```

---

## commands/status/register.py

Extract `status` command and contribute to `/items` (currently in server.py).
The `/items` route and `/sources` route belong logically to the listing
infrastructure — put them in status's router.

```python
# commands/status/register.py
from __future__ import annotations
import click
from fastapi import APIRouter
from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:

    @click.command("status")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def status_cmd(ctx, fmt, **kwargs):
        _, _, store = build_engine(ctx.obj["verbose"])
        out(store.status(), fmt)

    return CommandManifest(
        name="status",
        click_command=status_cmd,
        api_router=_build_router(plugin_manifests),
    )


def _build_router(plugin_manifests: dict) -> APIRouter:
    router = APIRouter()

    @router.get("/sources")
    def sources():
        from core.config import load_config
        from core.registry import build_plugins
        config = load_config()
        return list(build_plugins(config).keys())

    @router.get("/items")
    def items(
        source: str | None = None,
        limit: int = 50,
        video_type: str | None = None,
        min_duration: int | None = None,
        max_duration: int | None = None,
        since: str | None = None,
        until: str | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
    ):
        from core.config import load_config
        from storage.sqlite_store import SQLiteStore, SearchFilters
        config = load_config()
        store = SQLiteStore(config.get("db_path", ":memory:"))
        filters = SearchFilters(source=source, video_type=video_type,
            min_duration=min_duration, max_duration=max_duration,
            since=since, until=until, min_size=min_size, max_size=max_size)
        return store.list_documents(source, limit, filters)

    return router
```

---

## commands/reindex/register.py

Extract `reindex` command and `POST /reindex`.

```python
# commands/reindex/register.py
from __future__ import annotations
import click
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command("reindex")
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def reindex_cmd(ctx, source, fmt, **kwargs):
        engine, plugins, _ = build_engine(ctx.obj["verbose"])
        targets = list(plugins.keys()) if source == "all" else [source]
        results = []
        for name in targets:
            r = engine.reindex(plugins[name])
            results.append({"source": r.source, "documents": r.documents, "chunks": r.chunks})
        out(results, fmt)

    return CommandManifest(
        name="reindex",
        click_command=reindex_cmd,
        api_router=_build_router(source_choices),
    )


def _build_router(source_choices: list[str]) -> APIRouter:
    router = APIRouter()

    class ReindexRequest(BaseModel):
        source: str

    @router.post("/reindex")
    def reindex(req: ReindexRequest):
        from core.config import load_config
        from core.embedder import Embedder
        from core.registry import build_plugins
        from core.sync_engine import SyncEngine
        from storage.sqlite_store import SQLiteStore
        if req.source not in source_choices:
            raise HTTPException(status_code=400, detail="Unknown source")
        config = load_config()
        store = SQLiteStore(config.get("db_path", ":memory:"))
        embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
        engine = SyncEngine(store, embedder)
        plugins = build_plugins(config)
        r = engine.reindex(plugins[req.source])
        return {"source": r.source, "documents": r.documents, "chunks": r.chunks}

    return router
```

---

## commands/serve/register.py

```python
# commands/serve/register.py
from __future__ import annotations
import click
from commands.base import CommandManifest
from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> CommandManifest:

    @click.command("serve")
    @click.option("--port", type=int, default=8000)
    @click.pass_context
    def serve_cmd(ctx, port, **kwargs):
        import uvicorn
        _configure_logging(ctx.obj["verbose"])
        uvicorn.run("api.server:app", host="0.0.0.0", port=port, reload=False)

    return CommandManifest(name="serve", click_command=serve_cmd)
```

---

## commands/setup/register.py

```python
# commands/setup/register.py
from __future__ import annotations
import click
from commands.base import CommandManifest
from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> CommandManifest:

    @click.command("setup")
    @click.pass_context
    def setup_cmd(ctx, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        from setup_wizard import run_wizard
        run_wizard()

    return CommandManifest(name="setup", click_command=setup_cmd)
```

---

## AGENTS.md files

Create a minimal `AGENTS.md` in each command directory. Example for `search/`:

```markdown
# commands/search/

Implements the `corpus search` CLI command and the GET /search API endpoint.

## Extension points

Plugins contribute additional filter options via `plugin_manifest.cli_options["search"]`.
The command callback passes all kwargs to `make_filters()` which maps them to
SearchFilters fields. To add a new filter:
1. Add a click.Option to your plugin's `cli_options["search"]`
2. Add the corresponding field to SearchFilters in storage/sqlite_store.py

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
```

Create equivalent minimal AGENTS.md for sync, get, delete, status, reindex,
serve, setup.

---

## Add make_filters to commands/helpers.py

Add this function to `commands/helpers.py` (import inspect at top of file):

```python
import inspect
from storage.sqlite_store import SearchFilters

_SF_PARAMS = set(inspect.signature(SearchFilters.__init__).parameters) - {"self"}

def make_filters(**kwargs) -> SearchFilters:
    """Build SearchFilters from kwargs, ignoring unrecognized keys."""
    return SearchFilters(**{k: v for k, v in kwargs.items() if k in _SF_PARAMS})
```

---

## Verification

After completing this phase, verify the command register functions work in
isolation — WITHOUT touching `cli/main.py` or `api/server.py`:

```python
# Smoke test — run from corpus-agent directory
from core.config import load_config
from core.registry import discover_plugins, discover_commands

config = load_config()
plugin_manifests = discover_plugins(config)
command_manifests = discover_commands(plugin_manifests)

print("commands:", list(command_manifests.keys()))
# expect: ['delete', 'get', 'reindex', 'search', 'serve', 'setup', 'status', 'sync']

# Verify search has plugin options injected
search = command_manifests["search"].click_command
param_names = [p.name for p in search.params]
print("search params:", param_names)
assert "privacy_status" in param_names, "youtube options not injected"
assert "since" in param_names, "obsidian options not injected"
assert "min_duration" in param_names

# Verify --source in sync is dynamic
sync = command_manifests["sync"].click_command
source_param = next(p for p in sync.params if p.name == "source")
print("sync --source choices:", source_param.type.choices)
assert "obsidian" in source_param.type.choices
assert "youtube" in source_param.type.choices
assert "all" in source_param.type.choices

print("Phase 3 verification passed.")
```

Also run the full test suite — all existing tests must still pass:

```bash
python -m pytest tests/ -x -q
```

---

## What this phase does NOT do

- Does not modify `cli/main.py` or `api/server.py`.
- The actual CLI entry point and HTTP server still use the old monolith.
- The new command registers exist but are not wired yet.

# Phase 4 — Wiring + Test Suite

## Context

You are working on `corpus-agent`. This is the FINAL phase (4 of 4).

Phases 1–3 added:
- `PluginManifest` / `CommandManifest` dataclasses
- `discover_plugins()` / `discover_commands()` in `core/registry.py`
- `plugins/obsidian/register.py`, `plugins/youtube/register.py`
- All `commands/<n>/register.py` files with extracted logic + API routers

This phase:
1. Replaces `cli/main.py` with a thin loader
2. Replaces `api/server.py` with a thin loader
3. Adds the `/api/frontend-fragments` endpoint
4. Updates `frontend/*.html` with the fragment bootstrap script
5. Deletes the now-dead `setconfig` command from wherever it landed
   (check: it was in `cli/main.py` — it must move to `commands/setconfig/register.py`)
6. Writes the full integration test suite
7. Updates `pyproject.toml`

**After this phase the old `cli/main.py` monolith is gone and the system
is fully modular.**

---

## Before you start

Read the current `cli/main.py` and `api/server.py` in full.
Identify any logic NOT yet covered by a command register.py —
specifically the `setconfig` command. Create `commands/setconfig/` before
rewriting `cli/main.py`.

---

## Files to create or modify

```
commands/setconfig/       CREATE: __init__.py, register.py, AGENTS.md
cli/main.py               REWRITE — thin loader
api/server.py             REWRITE — thin loader
frontend/index.html       MODIFY — add fragment bootstrap
frontend/search.html      MODIFY — add fragment bootstrap
frontend/items.html       MODIFY — add fragment bootstrap
frontend/status.html      MODIFY — add fragment bootstrap
tests/conftest.py         MODIFY — add fixtures
tests/test_cli.py         REWRITE — full integration tests
tests/test_api.py         REWRITE — full integration tests
pyproject.toml            MODIFY — add new packages
.doc/skills/              CREATE directory + two skill files
```

---

## Task 1: commands/setconfig/register.py

Extract the `setconfig` command verbatim from `cli/main.py`.
It has no API router. No plugin options are injected.

```python
# commands/setconfig/register.py
from __future__ import annotations
import click
from commands.base import CommandManifest
from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> CommandManifest:

    @click.command("setconfig")
    @click.pass_context
    def setconfig_cmd(ctx, **kwargs):
        """Interactively edit config.yaml settings."""
        _configure_logging(ctx.obj["verbose"])
        # ... paste the full setconfig body from cli/main.py here verbatim ...

    return CommandManifest(name="setconfig", click_command=setconfig_cmd)
```

---

## Task 2: Rewrite cli/main.py

The new `cli/main.py` must be ~25 lines. It:
- Declares the root `@click.group()` with `--verbose`
- Calls `discover_plugins()` and `discover_commands()` from `core/registry.py`
- Adds each `CommandManifest.click_command` to the group
- Has no knowledge of any plugin name, any option name, or any command logic

```python
# cli/main.py
from __future__ import annotations

import click

from core.config import load_config
from core.registry import discover_plugins, discover_commands


@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show logs on stderr.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


def _load() -> None:
    config = load_config()
    plugin_manifests = discover_plugins(config)
    command_manifests = discover_commands(plugin_manifests)
    for cm in command_manifests.values():
        main.add_command(cm.click_command)


_load()

if __name__ == "__main__":
    main()
```

---

## Task 3: Rewrite api/server.py

The new `api/server.py` must:
- Create the FastAPI app
- Include all API routers from command and plugin manifests
- Keep the frontend HTML file routes (these are infrastructure, not plugin logic)
- Add the `/api/frontend-fragments` endpoint
- Have no knowledge of any plugin name or route path

```python
# api/server.py
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from core.config import load_config
from core.registry import discover_plugins, discover_commands

app = FastAPI(title="corpus-agent")

_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def _html(name: str) -> HTMLResponse:
    path = _FRONTEND / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Frontend file missing: {path}")
    return HTMLResponse(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Frontend routes (infrastructure — not plugin-specific)
# ---------------------------------------------------------------------------

@app.get("/", response_class=RedirectResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui")

@app.get("/ui", response_class=HTMLResponse)
def ui_home() -> HTMLResponse:
    return _html("index.html")

@app.get("/ui/items", response_class=HTMLResponse)
def ui_items() -> HTMLResponse:
    return _html("items.html")

@app.get("/ui/search", response_class=HTMLResponse)
def ui_search() -> HTMLResponse:
    return _html("search.html")

@app.get("/ui/status", response_class=HTMLResponse)
def ui_status() -> HTMLResponse:
    return _html("status.html")


# ---------------------------------------------------------------------------
# Fragment API — serves all plugin/command JS contributions to the frontend
# ---------------------------------------------------------------------------

@app.get("/api/frontend-fragments")
def frontend_fragments() -> list[dict]:
    """Return all JS fragments registered by plugins and commands."""
    config = load_config()
    plugin_manifests = discover_plugins(config)
    command_manifests = discover_commands(plugin_manifests)
    frags = []
    for pm in plugin_manifests.values():
        if pm.frontend_js:
            frags.append({"source": pm.name, "kind": "plugin", "js": pm.frontend_js})
    for cm in command_manifests.values():
        if cm.frontend_js:
            frags.append({"source": cm.name, "kind": "command", "js": cm.frontend_js})
    return frags


# ---------------------------------------------------------------------------
# Auto-wire all command and plugin API routers
# ---------------------------------------------------------------------------

def _load() -> None:
    config = load_config()
    plugin_manifests = discover_plugins(config)
    command_manifests = discover_commands(plugin_manifests)
    for pm in plugin_manifests.values():
        if pm.api_router:
            app.include_router(pm.api_router)
    for cm in command_manifests.values():
        if cm.api_router:
            app.include_router(cm.api_router)


_load()
```

---

## Task 4: Add fragment bootstrap to frontend HTML files

In each of `frontend/index.html`, `frontend/search.html`, `frontend/items.html`,
`frontend/status.html`, add the following snippet just before the closing
`</body>` tag:

```html
<script>
  fetch('/api/frontend-fragments')
    .then(r => r.json())
    .then(frags => frags.forEach(f => {
      const s = document.createElement('script');
      s.textContent = f.js;
      document.head.appendChild(s);
    }))
    .catch(() => {});
</script>
```

This is a no-op today (no plugin has frontend_js yet) but wires the slot.

---

## Task 5: Update pyproject.toml

Add to `[tool.setuptools] packages`:

```toml
"commands",
"commands.sync",
"commands.search",
"commands.get",
"commands.delete",
"commands.status",
"commands.reindex",
"commands.serve",
"commands.setup",
"commands.setconfig",
```

---

## Task 6: Test suite

### tests/conftest.py — add these fixtures

Keep all existing fixtures. Add:

```python
import json
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from pathlib import Path
from unittest.mock import patch

from plugins.youtube.plugin import Transport


class MockYouTubeTransport(Transport):
    """Returns 2 deterministic fake videos with transcripts."""

    def get_uploads_playlist(self, channel_id: str) -> str:
        return "PLfake"

    def iter_playlist_pages(self, playlist_id: str):
        yield [
            {"snippet": {
                "resourceId": {"videoId": "vid1"},
                "title": "Video One",
                "publishedAt": "2024-01-15T00:00:00Z",
            }},
            {"snippet": {
                "resourceId": {"videoId": "vid2"},
                "title": "Video Two",
                "publishedAt": "2024-02-20T00:00:00Z",
            }},
        ]

    def get_video_details(self, video_ids: list[str]) -> dict:
        return {
            vid: {
                "contentDetails": {"duration": "PT5M30S"},
                "snippet": {
                    "description": f"Description for {vid}",
                    "title": f"Video {vid}",
                    "publishedAt": "2024-01-15T00:00:00Z",
                },
                "status": {"privacyStatus": "public"},
            }
            for vid in video_ids
        }

    def get_transcript(self, video_id: str, cookies) -> str:
        return f"transcript content for video {video_id}"

    def download_audio(self, video_id: str, cookies):
        return None


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Minimal Obsidian vault with 3 notes."""
    (tmp_path / "note1.md").write_text("# Hello World\nhello world content", encoding="utf-8")
    (tmp_path / "note2.md").write_text("# Foo Bar\nfoo bar baz content", encoding="utf-8")
    (tmp_path / "note3.md").write_text(
        "---\ntags:\n  - test\n---\n# Tagged Note\ntagged content", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def config_path(tmp_path: Path, vault: Path) -> Path:
    """Write a minimal config.yaml to tmp_path."""
    import yaml as _yaml  # the local yaml shim
    cfg = {
        "db_path": str(tmp_path / "test.db"),
        "embed_batch_size": 2,
        "obsidian": {"vault_path": str(vault)},
        "youtube": {"channel_id": "UC_fake", "client_secret_path": ""},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(_yaml.safe_dump(cfg), encoding="utf-8")
    return cfg_path


@pytest.fixture
def mock_env(config_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """
    Patch the environment so all components use:
    - config.yaml from tmp_path
    - YouTubePlugin with MockYouTubeTransport
    - DummyEmbedder (no real ML model needed)
    """
    monkeypatch.chdir(tmp_path)

    # Patch YouTubePlugin to always use MockYouTubeTransport
    from plugins.youtube import plugin as yt_plugin
    original_init = yt_plugin.YouTubePlugin.__init__

    def patched_init(self, config, transport=None):
        original_init(self, config, transport=MockYouTubeTransport())

    monkeypatch.setattr(yt_plugin.YouTubePlugin, "__init__", patched_init)

    # Patch Embedder to use DummyEmbedder
    from tests.conftest import DummyEmbedder
    import core.sync_engine as se
    import core.embedder as emb_mod
    monkeypatch.setattr(emb_mod, "Embedder", DummyEmbedder)

    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def api_client(mock_env) -> TestClient:
    """
    FastAPI TestClient. Import app AFTER mock_env is set up so
    module-level _load() picks up patched components.
    """
    # Force re-import so _load() runs with patched environment
    import importlib
    import api.server as srv
    importlib.reload(srv)
    return TestClient(srv.app)
```

**Note on DummyEmbedder**: The existing `conftest.py` defines `DummyEmbedder`
as a local class. Move it to a named fixture or reference it by its definition.
Ensure `mock_env` can import it.

---

### tests/test_cli.py — full integration tests

```python
# tests/test_cli.py
from __future__ import annotations
import json
import pytest
from cli.main import main


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def test_sync_obsidian(runner, mock_env):
    result = runner.invoke(main, ["sync", "--source", "obsidian", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["source"] == "obsidian"
    assert data[0]["indexed"] >= 1


def test_sync_youtube(runner, mock_env):
    result = runner.invoke(main, ["sync", "--source", "youtube", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["source"] == "youtube"
    assert data[0]["indexed"] >= 1


def test_sync_all(runner, mock_env):
    result = runner.invoke(main, ["sync", "--source", "all", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    sources = {r["source"] for r in data}
    assert "obsidian" in sources
    assert "youtube" in sources


def test_sync_clean(runner, mock_env):
    # Sync twice; second with --clean should re-index
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["sync", "--source", "obsidian", "--clean", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["indexed"] >= 1


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_search_keyword(runner, mock_env):
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["search", "hello", "--mode", "keyword", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data) >= 1
    assert any("note1" in r["handle"] or "hello" in r["title"].lower() for r in data)


def test_search_semantic(runner, mock_env):
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["search", "hello world", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)


def test_search_text_output(runner, mock_env):
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["search", "hello", "--mode", "keyword"])
    assert result.exit_code == 0, result.output
    assert "score=" in result.output


def test_search_no_results(runner, mock_env):
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["search", "xyzzy_nonexistent_zzz", "--mode", "keyword"])
    assert result.exit_code == 0
    assert "no results" in result.output


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

def test_get_meta(runner, mock_env):
    runner.invoke(main, ["sync", "--source", "obsidian"])
    search = runner.invoke(main, ["search", "hello", "--mode", "keyword", "--format", "json"])
    handle = json.loads(search.output)[0]["handle"]
    result = runner.invoke(main, ["get", handle, "--what", "meta", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["handle"] == handle
    assert "raw_text" not in data


def test_get_content(runner, mock_env):
    runner.invoke(main, ["sync", "--source", "obsidian"])
    search = runner.invoke(main, ["search", "hello", "--mode", "keyword", "--format", "json"])
    handle = json.loads(search.output)[0]["handle"]
    result = runner.invoke(main, ["get", handle, "--what", "content"])
    assert result.exit_code == 0
    assert "hello" in result.output.lower()


def test_get_not_found(runner, mock_env):
    result = runner.invoke(main, ["get", "ob-nonexistent-0000"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_by_handle(runner, mock_env):
    runner.invoke(main, ["sync", "--source", "obsidian"])
    search = runner.invoke(main, ["search", "hello", "--mode", "keyword", "--format", "json"])
    handle = json.loads(search.output)[0]["handle"]
    result = runner.invoke(main, ["delete", handle, "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["deleted"] is True
    # Confirm it's gone
    get_result = runner.invoke(main, ["get", handle])
    assert get_result.exit_code == 1


def test_delete_not_found(runner, mock_env):
    result = runner.invoke(main, ["delete", "ob-nonexistent-0000"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_status_after_sync(runner, mock_env):
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["status", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert any(r["source_plugin"] == "obsidian" for r in data)


def test_status_empty(runner, mock_env):
    result = runner.invoke(main, ["status", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Reindex
# ---------------------------------------------------------------------------

def test_reindex(runner, mock_env):
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["reindex", "--source", "obsidian", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["source"] == "obsidian"
    assert data[0]["documents"] >= 1
    assert data[0]["chunks"] >= 1


# ---------------------------------------------------------------------------
# Plugin option injection (structural tests — not behavior)
# ---------------------------------------------------------------------------

def test_plugin_options_in_search_help(runner, mock_env):
    """youtube and obsidian options must appear in corpus search --help."""
    result = runner.invoke(main, ["search", "--help"])
    assert result.exit_code == 0
    # YouTube options
    assert "--privacy-status" in result.output
    assert "--min-duration" in result.output
    assert "--max-duration" in result.output
    assert "--type" in result.output
    # Obsidian options
    assert "--since" in result.output
    assert "--until" in result.output
    assert "--min-size" in result.output


def test_plugin_options_not_in_status_help(runner, mock_env):
    """Filter options must NOT bleed into commands that don't accept them."""
    result = runner.invoke(main, ["status", "--help"])
    assert result.exit_code == 0
    assert "--privacy-status" not in result.output
    assert "--min-duration" not in result.output


def test_source_choices_are_dynamic(runner, mock_env):
    """--source choices come from discovered plugins, not hardcoded strings."""
    result = runner.invoke(main, ["sync", "--help"])
    assert "obsidian" in result.output
    assert "youtube" in result.output


# ---------------------------------------------------------------------------
# Modularity: plugin removal simulation
# ---------------------------------------------------------------------------

def test_plugin_removal_simulation(runner, mock_env, monkeypatch):
    """
    Simulate deleting the youtube plugin by patching discover_plugins to
    return only obsidian. Verify:
    - CLI does not crash
    - --privacy-status is gone from search --help
    - --source youtube is an invalid choice for sync
    """
    from core import registry as reg

    original = reg.discover_plugins

    def obsidian_only(config):
        all_p = original(config)
        return {k: v for k, v in all_p.items() if k == "obsidian"}

    monkeypatch.setattr(reg, "discover_plugins", obsidian_only)

    # Reload main so _load() runs with patched discover_plugins
    import importlib
    import cli.main as cli_mod
    importlib.reload(cli_mod)
    from cli.main import main as reloaded_main

    result = runner.invoke(reloaded_main, ["search", "--help"])
    assert result.exit_code == 0
    assert "--privacy-status" not in result.output, \
        "--privacy-status should be absent when youtube plugin is removed"

    result = runner.invoke(reloaded_main, ["sync", "--source", "youtube"])
    assert result.exit_code != 0, \
        "--source youtube should fail when youtube plugin is removed"
```

---

### tests/test_api.py — rewrite

```python
# tests/test_api.py
from __future__ import annotations
import pytest


def test_sources(api_client):
    resp = api_client.get("/sources")
    assert resp.status_code == 200
    sources = resp.json()
    assert "obsidian" in sources
    assert "youtube" in sources


def test_sync_obsidian(api_client):
    resp = api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "obsidian"
    assert "indexed" in data


def test_sync_unknown_source(api_client):
    resp = api_client.post("/sync", json={"source": "nonexistent"})
    assert resp.status_code == 400


def test_items_empty(api_client):
    resp = api_client.get("/items?limit=50")
    assert resp.status_code == 200
    assert resp.json() == []


def test_items_after_sync(api_client):
    api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    resp = api_client.get("/items?limit=50")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    assert all("title" in i for i in items)


def test_search_keyword(api_client):
    api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    resp = api_client.get("/search?q=hello&mode=keyword&limit=5")
    assert resp.status_code == 200
    results = resp.json()
    assert isinstance(results, list)


def test_search_bad_mode(api_client):
    resp = api_client.get("/search?q=hello&mode=invalid")
    assert resp.status_code == 400


def test_get_document(api_client):
    api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    items = api_client.get("/items?limit=10").json()
    assert items
    doc = items[0]
    resp = api_client.get(f"/document/{doc['source_plugin']}/{doc['source_id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == doc["title"]


def test_get_document_not_found(api_client):
    resp = api_client.get("/document/obsidian/nonexistent.md")
    assert resp.status_code == 404


def test_delete_document(api_client):
    api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    items = api_client.get("/items?limit=10").json()
    assert items
    doc = items[0]
    resp = api_client.delete(f"/document/{doc['source_plugin']}/{doc['source_id']}")
    assert resp.status_code == 200
    # Confirm deletion
    resp2 = api_client.get(f"/document/{doc['source_plugin']}/{doc['source_id']}")
    assert resp2.status_code == 404


def test_delete_document_not_found(api_client):
    resp = api_client.delete("/document/obsidian/ghost.md")
    assert resp.status_code == 404


def test_reindex(api_client):
    api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    resp = api_client.post("/reindex", json={"source": "obsidian"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "obsidian"
    assert data["documents"] >= 1


def test_frontend_fragments(api_client):
    resp = api_client.get("/api/frontend-fragments")
    assert resp.status_code == 200
    frags = resp.json()
    assert isinstance(frags, list)


def test_ui_home(api_client):
    resp = api_client.get("/ui", follow_redirects=True)
    assert resp.status_code == 200
    assert "corpus-agent" in resp.text


def test_ui_search_page(api_client):
    resp = api_client.get("/ui/search")
    assert resp.status_code == 200


def test_ui_items_page(api_client):
    resp = api_client.get("/ui/items")
    assert resp.status_code == 200


def test_ui_status_page(api_client):
    resp = api_client.get("/ui/status")
    assert resp.status_code == 200
```

---

## Task 7: Skill documentation

Create `.doc/skills/` directory and the following files:

### .doc/skills/HOW_TO_ADD_A_PLUGIN.md

```markdown
# How to add a new plugin

## Steps

1. Create `plugins/<name>/` with:
   - `__init__.py` (empty)
   - `plugin.py` — subclass `SourcePlugin`, implement `list_items()` and `fetch()`
   - `register.py` — implement `register(config) -> PluginManifest`
   - `AGENTS.md` — describe source, sync cursor, options

2. In `register.py`:
   ```python
   from plugins.base import PluginManifest
   from plugins.<name>.plugin import MyPlugin
   import click

   def register(config: dict) -> PluginManifest:
       return PluginManifest(
           name="<name>",
           source_plugin_class=MyPlugin,
           cli_options={
               "search": [
                   click.Option(["--my-filter"], type=int, default=None,
                                help="My plugin-specific filter."),
               ],
           },
       )
   ```

3. Add `"plugins.<name>"` to `[tool.setuptools] packages` in `pyproject.toml`.

4. Write tests:
   - Unit test for `plugin.py` in `tests/test_<name>.py`
   - Add CLI integration tests to `tests/test_cli.py`

## What happens automatically

The plugin is discovered by `core/registry.py` on next startup.
Its CLI options appear in the relevant commands' `--help`.
Its API router (if any) is included in the FastAPI app.
No changes to `cli/main.py`, `api/server.py`, or any other file.

## Note: --source option

Do NOT declare a `--source` option in your plugin. Commands build `--source`
dynamically from all registered plugin names.
```

### .doc/skills/HOW_TO_ADD_A_COMMAND.md

```markdown
# How to add a new command

## Steps

1. Create `commands/<name>/` with:
   - `__init__.py` (empty)
   - `register.py` — implement `register(plugin_manifests) -> CommandManifest`
   - `AGENTS.md` — describe what the command does and its extension points

2. In `register.py`:
   ```python
   import click
   from commands.base import CommandManifest
   from commands.helpers import build_engine, out

   def register(plugin_manifests: dict) -> CommandManifest:

       @click.command("<name>")
       @click.option("--format", "fmt",
                     type=click.Choice(["json", "text"]), default="text")
       @click.pass_context
       def my_cmd(ctx, fmt, **kwargs):
           engine, plugins, store = build_engine(ctx.obj["verbose"])
           # ... command logic ...
           out(result, fmt)

       # Inject any plugin options for this command
       for pm in plugin_manifests.values():
           my_cmd.params.extend(pm.cli_options.get("<name>", []))

       return CommandManifest(
           name="<name>",
           click_command=my_cmd,
           api_router=_build_router(),  # optional
       )
   ```

3. Add `"commands.<name>"` to `[tool.setuptools] packages` in `pyproject.toml`.

4. Write tests in `tests/test_cli.py` and `tests/test_api.py`.

## What happens automatically

The command is discovered and added to the CLI group on next startup.
Its API router (if any) is included in the FastAPI app.
No changes to `cli/main.py` or `api/server.py`.

## Receiving plugin-contributed options

Use `**kwargs` in the command callback to absorb injected options.
Pass them to `make_filters(**kwargs)` from `commands/helpers.py` if
the command supports filtering.
```

---

## Final verification

Run the complete test suite:

```bash
cd corpus-agent
python -m pytest tests/ -v
```

Expected: all tests pass, including the original unit tests.

Then verify the CLI entry point manually:

```bash
# From corpus-agent directory, with a valid config.yaml
corpus --help
# Must show: sync, search, get, delete, status, reindex, serve, setup, setconfig

corpus search --help
# Must show: --privacy-status, --min-duration, --since, --until, etc.

corpus sync --help
# Must show: --source with obsidian/youtube/all choices

# Verify old cli/main.py is GONE or reduced to ~25 lines
wc -l cli/main.py
# Should be ~25, not 300+
```

## Acceptance criteria

The refactoring is complete when:

1. `pytest tests/` passes — all unit tests and all new integration tests.
2. `wc -l cli/main.py` is under 30 lines.
3. `wc -l api/server.py` is under 60 lines.
4. `corpus search --help` shows `--privacy-status` and `--since`.
5. `test_plugin_removal_simulation` passes.
6. `GET /api/frontend-fragments` returns `[]` (no frontend_js yet — that's correct).
7. All 4 frontend pages load via `GET /ui*`.
8. Every new directory has an `AGENTS.md`.
