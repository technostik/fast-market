# toolsetup-cli

## 🎯 Purpose
Standalone CLI to configure global settings shared across all fast-market tools: LLM providers, workdir management, YouTube credentials, and agent config.

## 🏗️ Essential Components
- `toolsetup_entry/__init__.py` — package entry point, exports `main`
- `cli.py` — CLI bootstrap: wires `setup`, `autocomplete`, `config`, `backup`, `data` command groups
- `commands/setup/register.py` — main `toolsetup` group: wizard (no args), `llm`, `workdir`, `path`, `edit`, `show`, `clean-workdir`, `reset`, `reset-all`, `diagnose`
- `commands/setup/workdir.py` — `toolsetup workdir` subgroup: `init`, `show`, `reset`, `new`, `list`, `prev`, `last`, `lock`, `unlock`, `islocked`, `release`, `clean`
- `commands/setup/plugins/llm.py` — LLM config plugin (`~/.config/fast-market/common/llm/config.yaml`)
- `commands/setup/plugins/workdir.py` — workdir config plugin (`~/.config/fast-market/common/config.yaml`)
- `commands/setup/plugins/youtube.py` — YouTube config plugin
- `commands/setup/plugins/agent.py` — agent config plugin
- `commands/setup/diagnose.py` — health checks for workdir, LLM connectivity, YouTube API
- `commands/autocomplete/register.py` — `toolsetup autocomplete configure | list`
- `commands/backup/register.py` — `toolsetup backup snapshot | restore | rollback | list | status`
- `commands/config/register.py` — `toolsetup config clean-bak`
- `commands/data/register.py` — `toolsetup data list`
- `commands/snapshot_service.py` — tar-based snapshot/restore logic for workdir, config, data
- `commands/discovery.py` — discovers all `*-cli/pyproject.toml` entries in monorepo

## 📋 Core Responsibilities
- Manage LLM provider config (add, remove, set-default, list)
- Manage workdir: single-level via `clean-workdir`, multi-level via `workdir` subgroup with history navigation (prev/last) and lock/unlock
- Manage YouTube credentials and agent execution config
- Generate shell autocomplete scripts for all fast-market CLIs
- Snapshot/restore workdir, config, and data directories (tar-based)
- Run health diagnostics for workdir, LLM connectivity, and YouTube API

## 🔗 Dependencies & Integration
- Imports from: `common.core.config`, `common.core.paths`, `common.core.yaml_utils`, `common.agent.prompts`
- Used by: all other fast-market tools rely on configs written here
- External deps: `click`, `pyyaml`, `auto-click-auto` (shell completion), `uuid6`
- NO runtime dependency on any other agent CLI

## ✅ Do's
- Store only env var names for API keys — never store key values
- Use `get_plugin("llm")`, `get_plugin("workdir")` etc. to load/save configs consistently
- Back up existing configs before resetting (`reset`, `reset-all` do this automatically)
- Run `toolsetup diagnose` after major config changes to validate connectivity

## ❌ Don'ts
- Don't manage per-tool config here — each tool has its own `setup` command
- Don't store actual API key values in config files — only env var names (e.g., `ANTHROPIC_API_KEY`)
- Don't require any other agent CLI to be installed or running

## ⚠️ Pitfalls
- **reset-all overwrites everything**: `toolsetup reset-all` backs up then overwrites ALL tool configs discovered in the monorepo. Confirm with user before running.
- **workdir locking**: the `webux yt_poster` tab reads `is_workdir_locked()` via `toolsetup workdir islocked`/`workdir-status`; forgetting to unlock blocks workdir navigation in the UI.
- **autocomplete staleness**: completion scripts are generated once and cached in `~/.config/fast-market/completions/`. After adding new CLIs, re-run `toolsetup autocomplete configure --force`.
- **old vs new workdir**: `toolsetup clean-workdir` operates on the simple `workdir` path (single dir). `toolsetup workdir new/list/prev/last` operates on the `workdir_root`/`workdir` hierarchy. These are different config keys.

## 🧪 Tests
- No dedicated test directory for toolsetup — config management is validated across CLI integration tests
- Run monorepo tests: `pytest tests/ -v` from the monorepo root

## 🔍 Observability
- No structured logging (interactive config tool)
- `toolsetup diagnose` provides structured health-check output for workdir, LLM, and YouTube
- `toolsetup --show` shows all current config values
- `toolsetup --show-path` shows all config file paths

## 🛠️ Extension Points
- **Add a config plugin**: implement a plugin class in `commands/setup/plugins/<name>.py`, register in `all_plugins()` in `commands/setup/plugins/__init__.py`
- **Add a top-level command group**: create `commands/<name>/register.py`, add `register()` call in `cli.py`

## 📚 Related Documentation
- See `README.md` for complete command reference and examples
- See `common/AGENTS.md` for shared config utilities (`load_common_config`, `get_tool_config_path`)
