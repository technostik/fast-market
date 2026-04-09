# common/core Module

## Purpose
Provides foundational infrastructure for all fast-market agents, including path management, configuration loading, command registry, and alias resolution.

## Path Management

XDG-compliant paths under `fast-market` namespace for user-specific data:
- `XDG_CONFIG_HOME` (default: `~/.config`)
- `XDG_DATA_HOME` (default: `~/.local/share`)
- `XDG_CACHE_HOME` (default: `~/.cache`)

Common config files (in `~/.config/fast-market/common/` directory):
- `common/config.yaml` - workdir and other common settings
- `common/llm/config.yaml` - LLM providers configuration
- `common/youtube/config.yaml` - YouTube OAuth credentials

### Available Functions

| Function | Returns | Description |
|----------|---------|-------------|
| `get_common_config_path()` | `Path` | `~/.config/fast-market/common/config.yaml` |
| `get_llm_config_path()` | `Path` | `~/.config/fast-market/common/llm/config.yaml` |
| `get_youtube_config_path()` | `Path` | `~/.config/fast-market/common/youtube/config.yaml` |
| `get_common_subconfig_path(subconfig)` | `Path` | `~/.config/fast-market/common/{subconfig}/config.yaml` |
| `get_aliases_path()` | `Path` | `~/.config/fast-market/aliases.yaml` |
| `get_tool_config_path(tool_name)` | `Path` | `~/.config/fast-market/{tool}/config.yaml` |
| `get_prompts_dir()` | `Path` | `~/.local/share/fast-market/prompts/` |
| `get_skills_dir()` | `Path` | `~/.local/share/fast-market/skills/` |
| `get_data_dir()` | `Path` | `~/.local/share/fast-market/data/` |
| `get_cache_dir()` | `Path` | `~/.cache/fast-market/` |
| `get_tool_data_dir(tool_name)` | `Path` | `~/.local/share/fast-market/{tool}/` |
| `get_tool_cache_dir(tool_name)` | `Path` | `~/.cache/fast-market/{tool}/` |
| `get_tool_config(tool_name)` | `Path` | Alias for `get_tool_config_path()` |
| `get_fastmarket_dir()` | `Path` | Alias for `get_data_dir()` |

### Directory Creation
All path functions automatically create their parent directories on first call (`mkdir parents=True, exist_ok=True`).

## Configuration

### ConfigError
Exception raised when required configuration is missing or invalid:
- Config file exists but contains invalid YAML
- Config file exists but is not a YAML mapping
- Required common sub-config is missing (when tool declares requirement via `requires_common_config()`)
- No LLM configuration found when required
- No default LLM provider set when required

### Common Config (~/.config/fast-market/common/config.yaml)
```yaml
workdir: null    # optional global default working directory
```

### LLM Config (~/.config/fast-market/common/llm/config.yaml)
```yaml
default_provider: anthropic        # required for LLM commands
providers:
  anthropic:
    model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
  openai:
    model: gpt-4
    api_key_env: OPENAI_API_KEY
  ollama:
    model: llama3.2
    base_url: http://127.0.0.1:11434
  openai-compatible:
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_COMPATIBLE_API_KEY
```

### YouTube Config (~/.config/fast-market/common/youtube/config.yaml)
```yaml
client_secret_path: ~/.config/fast-market/common/youtube/client_secret.json
channel_id: UC...
quota_limit: 10000
```

### Tool Config (~/.config/fast-market/{tool}/config.yaml)
```yaml
llm:
  default_provider: ollama   # override default for this tool only
# tool-specific keys below
```

**Important:** Tool config can only override `llm.default_provider`, never the providers list. The `providers` section always comes from LLM config.

### Config Resolution

This section describes how `load_tool_config()` works.

**Declaration:** Tools must declare which common sub-configs they require via `requires_common_config()`:

```python
# In your tool's cli/main.py, BEFORE loading config
from common.core.config import requires_common_config

# Declare required common sub-configs
requires_common_config("task", ["llm"])          # Task needs LLM
requires_common_config("youtube", ["llm", "youtube"])  # YouTube needs both
requires_common_config("image", [])               # No common config needed
```

**Discovery:** All common sub-configs are auto-discovered by scanning `~/.config/fast-market/common/` for directories containing `config.yaml`.

**Resolution order** (later wins):
1. Common config (`~/.config/fast-market/common/config.yaml`)
2. Discovered common sub-configs (`~/.config/fast-market/common/*/config.yaml`)
3. Tool config (`~/.config/fast-market/{tool}/config.yaml`)

**Required vs Optional:**
- If a tool declares `requires_common_config("tool", ["llm"])`, and `llm/config.yaml` doesn't exist, `load_tool_config()` raises `ConfigError`
- Sub-configs not in the required list are optional — if they exist, they're merged; if not, they're silently skipped

**Merge strategy:** Deep merge. Tool config wins on conflicts.

### Config Loading Functions

- `requires_common_config(tool_name, required_subconfigs)` - Register tool's common config requirements
- `load_common_config()` - Load common/config.yaml
- `save_common_config(config)` - Save to common/config.yaml
- `load_llm_config()` - Load common/llm/config.yaml
- `save_llm_config(config)` - Save to common/llm/config.yaml
- `load_youtube_config()` - Load common/youtube/config.yaml
- `save_youtube_config(config)` - Save to common/youtube/config.yaml
- `load_tool_config(tool_name, path=None)` - Load effective config for a tool
- `resolve_llm_config(tool_name)` - Get LLM config for a tool
- `_deep_merge(base, override)` - Internal helper for config merging

## Registry

- `discover_commands()` - Auto-discovers CLI commands from `commands/*/register.py`
- `discover_plugins()` - Auto-discovers plugins from `plugins/*/plugin.py`
- `build_plugins(manifests)` - Builds plugin instances from manifests

## Duration Parsing

Two functions for parsing duration strings into seconds:

### `parse_duration(duration)`
Parses simple duration strings with suffixes:
- `'30s'` - 30 seconds
- `'10m'` - 10 minutes (600 seconds)
- `'1h'` - 1 hour (3600 seconds)
- `'2.5h'` - 2.5 hours (9000 seconds)
- `'300'` or `300` - plain seconds (backward compatible)
- `None` - returns `None`

Used for skill timeouts in SKILL.md frontmatter (`timeout: 10m`).

### `parse_iso_duration(iso_duration)`
Parses ISO 8601 duration strings:
- `'PT30S'` - 30 seconds
- `'PT10M'` - 10 minutes
- `'PT1H'` - 1 hour
- `'PT1H2M3S'` - 1 hour, 2 minutes, 3 seconds (3723 seconds)
- Falls back to `parse_duration()` for non-ISO formats

Used for YouTube video durations (`PT1H2M3S` format).

## Aliases

- `get_aliases_path()` - Returns aliases file path
- `load_aliases()` - Loads aliases from YAML
- `resolve_alias(alias)` - Resolves alias to command string
- `get_all_aliases()` - Returns all aliases as dict
- `create_or_update_alias(name, command, description)` - Creates/updates alias
- `remove_alias(name)` - Removes alias

## Do's
- Always use path functions from this module instead of hardcoding paths
- Respect XDG conventions for all file storage
- Use `requires_common_config()` before calling `load_tool_config()`
- Use `load_tool_config()` for any tool that needs configuration
- Use `resolve_llm_config()` when you need LLM settings specifically

## Don'ts
- Never hardcode `~/.config`, `~/.local/share`, or `~/.cache` for project configs
- Never create paths outside the `fast-market` namespace for user data
- Never write `llm.providers` to tool-specific config (it will be stripped)
- Never call `load_tool_config()` without first calling `requires_common_config()`
