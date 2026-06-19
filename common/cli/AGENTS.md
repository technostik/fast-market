# common/cli

## 🎯 Purpose
Shared Click helpers and output formatters for all fast-market CLI tools. Provides a standard group factory and a uniform output function so every CLI behaves consistently.

## 🏗️ Essential Components
- `base.py` — `create_cli_group(tool_name, description, default_command, default_args)` — creates a standard Click group with `--verbose/-v` flag and optional default-command dispatch
- `helpers.py` — `out(data, fmt)`, `get_editor()`, `open_editor(file_path)` — output formatting and editor integration

## 📋 Core Responsibilities
- Create a Click group that injects `verbose` and `tool_name` into `ctx.obj`
- Format output uniformly as JSON, YAML, or human-readable text
- Detect the user's preferred editor (via `GIT_EDITOR`, `$EDITOR`, then `nano`)

## 🔗 Dependencies & Integration
- Imports from: `common.core.yaml_utils` (for YAML output in `helpers.py`)
- Used by: every fast-market CLI's `cli/main.py` (`create_cli_group`) and command modules (`out`)
- External deps: `click`, `pyyaml`

## ✅ Do's
- Use `create_cli_group()` as the entry point for every new CLI tool
- Use `out(data, fmt)` for all command output — never `print()` directly in commands
- Read `ctx.obj["verbose"]` to decide whether to log progress messages

## ❌ Don'ts
- Do not add command-specific logic here — this is infrastructure only
- Do not bypass `out()` with raw `print()` in commands — it breaks `--format` consistency

## ⚠️ Pitfalls
- `out()` skips keys named `"raw_text"` in dict output — this is intentional to hide internal-only fields. Do not name user-facing fields `raw_text`.
- `get_editor()` runs `git var GIT_EDITOR` as a subprocess. In environments without git this falls back silently to `$EDITOR` then `nano`.

## 🛠️ Extension Points
- To add a new output format: extend the `if/elif` in `out()` in `helpers.py`
- To add global flags (e.g., `--config`): extend `create_cli_group()` in `base.py`

## 📚 Related Documentation
- See `README.md` for usage and CLI reference
- See `common/core/AGENTS.md` for path and config conventions
