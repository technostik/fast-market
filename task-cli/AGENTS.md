# task-agent

## 🎯 Purpose
Standalone agentic CLI (`task`) that drives an LLM to iteratively execute whitelisted CLI commands until a task is complete. Owns only the CLI wiring, command-whitelist config, and session reporting; the agentic loop itself lives in `common/agent/`.

## 🏗️ Essential Components
- `task_entry/__init__.py` — Entry point; discovers providers, wires commands, enforces common config
- `commands/task/register.py` — `apply` command: CLI options, workdir/param resolution, loop invocation, session metrics
- `commands/task/executor.py` — Command validation (whitelist, no `shell=True`, workdir jail), subprocess execution
- `commands/task/loop.py` — Re-exports `TaskConfig`, `TaskLoop`, `run_dry_run` from `common.agent`
- `commands/task/prompts.py` — System prompt builder (used by `show-sys-prompt`)
- `commands/task/command_registry.py` — Auto-extracts `--help` text from fast-market CLIs for the system prompt
- `commands/show_sys_prompt/register.py` — `show-sys-prompt` command: renders the full system prompt for inspection
- `commands/setup/register.py` — `setup` group: `show`, `edit`, `allowed-commands`, `set-max-iterations`, `set-timeout`, `set-workdir`, `reset`
- `commands/setup/__init__.py` — load/save/init task config from `~/.config/fast-market/common/agent/config.yaml`
- `commands/setup/task_edit.py` — Opens config in default editor with validation
- `core/session.py` — Re-exports `Session`, `Turn`, `ToolCallEvent` from `common.agent.session`
- `core/task_prompt.py` — `TaskPromptConfig` dataclass for prompt template management

## 📋 Core Responsibilities
- Accept a task description and execute it through the LLM-driven command loop
- Enforce the command whitelist (basename-only matching, no `shell=True`, forbidden workdirs)
- Resolve `--param key=value` / `key=@file` / `key=@-` (stdin) parameters before passing to LLM
- Generate the system prompt that gives the LLM documentation for all allowed commands
- Manage allowed-commands, max-iterations, timeout, and workdir defaults via `task setup`
- Save session YAML and surface metrics/failures via `task report`

## 🔗 Dependencies & Integration
- Imports from: `common.agent` (TaskLoop, TaskConfig, prompts, session), `common.core.config`, `common.llm.registry`, `common.core.paths`, `common.cli.base`, `common.prompt`
- Declared dependency on `prompt-agent` package (provides `common/` infrastructure)
- Agent config is **shared** with `skill-cli`: `~/.config/fast-market/common/agent/config.yaml`; `task setup reset` rewrites it with task defaults
- External deps: `click`, `pyyaml`

## ✅ Do's
- Keep commands thin — delegate loop logic to `common.agent.TaskLoop`
- Validate workdir against the forbidden-paths list in `_resolve_workdir()` before use
- Fail loudly: no provider → redirect to `toolsetup`; missing param file → `ValueError` with path
- Use relative `--save-session` paths as relative to workdir, absolute paths as-is
- Use `task setup allowed-commands add/remove` to adjust the whitelist at runtime

## ❌ Don'ts
- Do not add LLM configuration management — that belongs in `toolsetup`
- Do not re-implement prompt template management already in `common.prompt`
- Do not allow `shell=True` in subprocess execution (security boundary)
- Do not allow workdirs that are `/`, `/bin`, `/usr`, `/etc`, or other system paths

## ⚠️ Pitfalls
- `default_command="apply"` in `create_cli_group` means `task "desc"` works as shorthand for `task apply "desc"` — the CLI group is named `apply` internally, which is confusing when reading `task_entry/__init__.py`
- Shared agent config with `skill-cli` means `task setup reset` also resets skill agent defaults; always verify after reset

## 🧪 Tests
- No dedicated test directory currently
- Test file: confirm behavior with `task apply "echo hello world" --workdir /tmp --dry-run`
- Run with: `task report .last-session.yaml` to verify session output

## 🔍 Observability
- `--debug normal` — shows provider/model selection
- `--debug full` — dumps full session YAML to stderr after completion
- `--silent` — suppresses session header and metrics
- Session metrics printed to stderr after completion: tool calls, rounds, errors, guesses, success rate
- `task report <session.yaml>` — structured view of metrics and failed commands

## 🛠️ Extension Points
**To add a command to the default whitelist:**
- Add to `fastmarket_tools` or `system_commands` in `_default_agent_config()` in `commands/setup/register.py`
- Or at runtime: `task setup allowed-commands add <name>`

**To customize the system prompt template:**
- Edit `agent_prompt.templates.default` in `~/.config/fast-market/common/agent/config.yaml`
- Or: `task setup edit`

**To add a new setup subcommand:**
- Add a `@setup_cmd.command(...)` inside `register()` in `commands/setup/register.py`

**To add a new top-level command:**
1. Create `commands/<name>/register.py` returning `CommandManifest`
2. Register it in `task_entry/__init__.py` with `main.add_command(...)`

## 📚 Related Documentation
- See `README.md` for usage, installation, and CLI reference
- See `common/agent/AGENTS.md` for the TaskLoop implementation
- See `skill-cli/AGENTS.md` for how skills use the same TaskLoop
- See `prompt-cli/AGENTS.md` for prompt template management
