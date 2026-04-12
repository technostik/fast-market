# Refactoring Prompt: Centralized Data Directory for Fast-Market

## Context
I'm building **fast-market**, a suite of agentic tools (including `corpus-agent`). Currently, `corpus-agent` looks for `config.yaml` in the current directory and stores its database in a project-relative path.

## Goal
Centralize all fast-market application data into a single, well-known location following Linux conventions, while maintaining modularity (each tool can be independently deleted/disabled).

## Requirements

### 1. Single Root Directory
All fast-market data lives under: `~/.local/share/fast-market/`

Structure:
```
~/.config/fast-market/         # Configuration (XDG_CONFIG_HOME)
├── corpus/
│   └── config.yaml      # corpus-agent specific config
├── monitor/
│   └── config.yaml      # monitor-agent specific config
└── ...

~/.local/share/fast-market/    # Data (XDG_DATA_HOME)
├── data/                # Tool-specific data
│   ├── corpus/          # corpus-agent database and indexes
│   │   └── corpus.db
│   ├── monitor/         # monitor-agent data
│   └── ...
└── ...

~/.cache/fast-market/          # Cache (XDG_CACHE_HOME)
└── corpus/
```

### 2. Modularity Preservation
- Deleting `~/.local/share/fast-market/data/corpus/` should remove all corpus-agent data
- Deleting `~/.config/fast-market/corpus/config.yaml` should reset corpus-agent config
- Other tools remain unaffected

### 3. Code Changes Required

#### A. Add path resolution utility
Create `core/paths.py`:
```python
from pathlib import Path
import os

def get_fastmarket_dir() -> Path:
    """Return the base directory for all fast-market data."""
    # Respect XDG_DATA_HOME if set, otherwise default to ~/.local/share
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "fast-market"

def get_tool_config(tool_name: str) -> Path:
    """Return path to tool's config file."""
    return get_fastmarket_dir() / "config" / f"{tool_name}.yaml"

def get_tool_data_dir(tool_name: str) -> Path:
    """Return path to tool's data directory (created if needed)."""
    path = get_fastmarket_dir() / "data" / tool_name
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_tool_cache_dir(tool_name: str) -> Path:
    """Return path to tool's cache directory (created if needed)."""
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    path = cache_home / "fast-market" / tool_name
    path.mkdir(parents=True, exist_ok=True)
    return path
```

#### B. Update config loading
`core/config.py` should:
- Look for `config.yaml` in `~/.config/fast-market/corpus/`
- Fall back to environment variable `FASTMARKET_CONFIG_DIR` for testing/overrides
- Still support `:memory:` for database

#### C. Update database initialization
`storage/sqlite_store.py` should:
- Use `get_tool_data_dir("corpus") / "corpus.db"` as default
- Keep `:memory:` special case

#### D. Update setup wizard
`setup_wizard.py` should:
- Create the directory structure
- Write config to the new location
- Print clear paths to user

#### E. Update documentation
`README.md` should:
- Document where data lives
- Show how to completely reset corpus-agent (delete the directories)

### 4. Backward Compatibility (Optional but nice)
If `config.yaml` exists in current directory, use it with a warning:
```python
import warnings
warnings.warn("config.yaml in current directory is deprecated. Move to ~/.config/fast-market/corpus/config.yaml")
```

### 5. Testing
Update tests to:
- Use temporary directories (pytest's `tmp_path`)
- Mock the path resolution functions
- Verify isolation between tools

## Expected Outcome
- Clean, standard Linux directory layout
- Single source of truth for all fast-market tools
- Each tool remains independently removable
- Easy for users to backup, reset, or inspect

## Non-Goals
- Changing the plugin/command architecture
- Modifying core business logic
- Breaking existing user setups (handle gracefully)

### Issue description
The README now shows `db_path` using `~`, and users may set `FASTMARKET_CONFIG_DIR`/XDG env vars using `~`, but the code treats these strings literally (no `expanduser()`), causing config/db/vault paths to resolve incorrectly.

### Issue Context
- `load_config()` builds config paths from `FASTMARKET_CONFIG_DIR` using `Path(override_dir)`.
- `get_fastmarket_dir()`/`get_tool_cache_dir()` read XDG env vars using `Path(env_value)`.
- `SQLiteStore` passes `db_path` directly to `sqlite3.connect()`.
- Plugins construct `Path(...)` from configured paths directly.

### Fix Focus Areas
- corpus-agent/core/config.py[12-30]
- corpus-agent/core/paths.py[7-30]
- corpus-agent/storage/sqlite_store.py[18-25]
- corpus-agent/plugins/obsidian/plugin.py[19-27]
- corpus-agent/plugins/youtube/plugin.py[74-75]
- corpus-agent/tests/test_paths_config.py[33-42]