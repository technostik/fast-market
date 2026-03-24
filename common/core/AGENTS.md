# common/core Module

## Purpose
Provides foundational infrastructure for all fast-market agents, including path management, configuration loading, command registry, and alias resolution.

## Path Management

XDG-compliant paths under `fast-market` namespace for user-specific data:
- `XDG_CONFIG_HOME` (default: `~/.config`)
- `XDG_DATA_HOME` (default: `~/.local/share`)
- `XDG_CACHE_HOME` (default: `~/.cache`)

Project-level config files (in `common/` directory):
- `common/config.yaml` - workdir and other common settings
- `common/llm/config.yaml` - LLM providers configuration

### Available Functions

| Function | Returns | Description |
|----------|---------|-------------|
| `get_common_config_path()` | `Path` | `common/config.yaml` |
| `get_llm_config_path()` | `Path` | `common/llm/config.yaml` |
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
- No LLM configuration found when required
- No default LLM provider set when required

### Common Config (common/config.yaml)
```yaml
workdir: null    # optional global default working directory
```

### LLM Config (common/llm/config.yaml)
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

### Tool Config (~/.config/fast-market/{tool}/config.yaml)
```yaml
llm:
  default_provider: ollama   # override default for this tool only
# tool-specific keys below
```

**Important:** Tool config can only override `llm.default_provider`, never the providers list. The `providers` section always comes from LLM config.

### Config Loading Functions

- `load_common_config()` - Load common/config.yaml
- `save_common_config(config)` - Save to common/config.yaml
- `load_llm_config()` - Load common/llm/config.yaml
- `save_llm_config(config)` - Save to common/llm/config.yaml
- `load_tool_config(tool_name, path=None)` - Load effective config for a tool
- `resolve_llm_config(tool_name)` - Get LLM config for a tool
- `_deep_merge(base, override)` - Internal helper for config merging

**Resolution order (later wins):**
1. Common config (common/config.yaml)
2. LLM config (common/llm/config.yaml)
3. Tool config (~/.config/fast-market/{tool}/config.yaml)

## Registry

- `discover_commands()` - Auto-discovers CLI commands from `commands/*/register.py`
- `discover_plugins()` - Auto-discovers plugins from `plugins/*/plugin.py`
- `build_plugins(manifests)` - Builds plugin instances from manifests

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
- Use `load_tool_config()` for any tool that needs configuration
- Use `resolve_llm_config()` when you need LLM settings specifically

## Don'ts
- Never hardcode `~/.config`, `~/.local/share`, or `~/.cache` for project configs
- Never create paths outside the `fast-market` namespace for user data
- Never write `llm.providers` to tool-specific config (it will be stripped)
