# ADR-001: Shared YouTube Config & Plugin-Based toolsetup

**Status:** Accepted
**Date:** 2026-04-13
**Context:** fast-market multi-tool configuration

## Problem

Multiple CLI tools (`corpus-cli`, `youtube-cli`, `monitor-cli`) each managed their own YouTube `channel_id` and `client_secret.json` path in separate config files. This led to:

1. **Duplication** — the same `channel_id` was stored in every tool's config
2. **Inconsistency** — each tool had different prompts, validation, and UX for setup
3. **Maintenance burden** — changing the YouTube channel required editing N config files
4. **No unified editing** — `toolsetup edit` only handled `--llm`, `--common`, `--agent` with no extensible way to add more

## Decision

### 1. Shared YouTube Config

Move `channel_id` and `client_secret_path` to a single shared location:
```
~/.config/fast-market/common/youtube/config.yaml
```

All tools read this via the existing config merge in `load_tool_config()`, which already discovers and merges `common/*/config.yaml` subconfigs into tool configs.

### 2. Smart Config Split on Write

Added `split_and_save_config(tool_name, config)` to `common/core/config.py`. When a tool wizard saves a merged config:
- The `youtube` section is extracted and written to `common/youtube/config.yaml`
- All other sections are written to the tool's own config file

### 3. Plugin Architecture for toolsetup

Created `toolsetup-cli/commands/setup/plugins/` with an abstract `ConfigPlugin` base class:

```python
class ConfigPlugin(ABC):
    name: str              # "youtube", "llm", "agent", "workdir"
    display_name: str      # human-readable label
    def config_path(self) -> Path
    def load(self) -> dict
    def save(self, config: dict) -> None
    def default_config(self) -> dict
    def ensure_exists(self) -> None
```

Each plugin self-registers on import via `register_plugin(Instance())`. This makes adding new subconfigs a matter of creating one file and one import line.

### 4. Renamed Commands

| Before | After |
|--------|-------|
| `youtube setup --create` | `youtube setup --wizard` |
| `toolsetup edit --common` | `toolsetup edit --workdir` (`--common` kept as alias) |
| `toolsetup edit` (opens one file) | `toolsetup edit` (opens ALL config files) |

New commands:
- `toolsetup show [--youtube\|--llm\|--workdir\|--agent]` — display config contents
- `toolsetup edit --youtube` — edit shared YouTube config
- `toolsetup reset --youtube` — reset shared YouTube config to defaults
- `toolsetup path --youtube` — show YouTube config file path

## Consequences

### Positive
- **Single source of truth** for YouTube credentials across all tools
- **Extensible** — new subconfig types require only a new plugin file
- **Consistent UX** — all `toolsetup` subcommands (`edit`, `show`, `reset`, `path`) use the same plugin-driven pattern
- **Backward compatible** — `--common` alias preserved, existing tool configs still work (the merge layer picks up shared youtube keys)

### Negative
- **Migration needed** — existing tools that wrote `youtube.channel_id` to their own config still work (tool config overrides common in the merge), but users should be encouraged to remove duplicate keys from tool configs
- **Slightly more complex save path** — wizards must use `split_and_save_config()` instead of a simple file write; forgetting this will write youtube keys to the tool config (which still works but defeats the sharing purpose)

### File Changes

| File | Change |
|------|--------|
| `common/core/config.py` | Added `split_and_save_config()`, `_extract_youtube_config()`, `_extract_tool_config()` |
| `common/core/paths.py` | No changes (already had `get_youtube_config_path()`) |
| `corpus-cli/setup_wizard.py` | Prompts for shared youtube config first, no longer stores channel_id in corpus config |
| `corpus-cli/commands/setup/subcommands/wizard.py` | Edits shared youtube channel_id, saves separately |
| `corpus-cli/commands/setup/subcommands/edit.py` | Opens both corpus and shared youtube configs; `--youtube` flag |
| `youtube-cli/commands/setup/register.py` | `--create` → `--wizard`, interactive prompts, saves to shared config |
| `toolsetup-cli/commands/setup/plugins/__init__.py` | **New** — `ConfigPlugin` base class + registry |
| `toolsetup-cli/commands/setup/plugins/youtube.py` | **New** — YouTube subconfig plugin |
| `toolsetup-cli/commands/setup/plugins/llm.py` | **New** — LLM subconfig plugin |
| `toolsetup-cli/commands/setup/plugins/agent.py` | **New** — Agent subconfig plugin |
| `toolsetup-cli/commands/setup/plugins/workdir.py` | **New** — Workdir/common subconfig plugin |
| `toolsetup-cli/commands/setup/register.py` | Rewritten `edit`, `reset`, `show`, `path` to use plugins; added `--youtube`, renamed `--common` → `--workdir` |
| `toolsetup-cli/pyproject.toml` | Added `commands.setup.plugins` package |

## Config Flow Diagram

```
┌─────────────────────────────────────┐
│  ~/.config/fast-market/common/      │
│    youtube/config.yaml              │  ← shared channel_id, client_secret_path
│    llm/config.yaml                  │  ← shared LLM providers
│    agent/config.yaml                │  ← shared agent prompts/templates
│    config.yaml                      │  ← shared workdir
└──────────────┬──────────────────────┘
               │ load_tool_config("corpus") merges ↑
               ▼
┌─────────────────────────────────────┐
│  ~/.config/fast-market/corpus/      │
│    config.yaml                      │  ← corpus-specific (db_path, obsidian, whisper)
└─────────────────────────────────────┘

On save: split_and_save_config() splits merged dict back into the two files.
```
