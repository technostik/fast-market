# common/agent

## 🎯 Purpose
Shared agentic loop for all fast-market CLI agents: runs an LLM-driven tool loop, executes whitelisted commands, manages session state, and provides inter-skill context passing. Extracted so both task-cli and skill-cli can use it without subprocess overhead.

## 🏗️ Essential Components
- `loop.py` — `TaskConfig`, `TaskLoop`, `run_dry_run()` — core LLM loop and configuration dataclass
- `session.py` — `Session`, `Turn`, `ToolCallEvent` — session data model and metrics
- `executor.py` — `CommandResult`, `execute_command()`, `resolve_and_execute_command()` — command execution with alias resolution
- `prompts.py` — `build_system_prompt()`, `render_command_documentation()` — LLM system prompt builder; exposes `DEFAULT_FASTMARKET_TOOLS`, `DEFAULT_SYSTEM_COMMANDS`
- `call.py` — `agent_call()` — high-level entry point; builds `TaskConfig`, resolves provider, runs the loop and returns a `Session`
- `doc.py` — `build_tool_documentation()`, `build_single_tool_doc()` — dynamic multi-level tool doc builder (calls `--help` at runtime on each tool)
- `shared_context.py` — `SharedContext`, `build_shared_context_tool()`, `execute_shared_context()` — read/write string shared between skills in a multi-skill run; persisted to disk

## 📋 Core Responsibilities
- Run an LLM → tool-call → feedback loop up to `max_iterations`
- Whitelist-guard all command execution via `TaskConfig.allowed_commands`
- Resolve aliases before executing commands (reads `~/.config/fast-market/aliases.yaml`)
- Record every turn and tool call in a `Session` for inspection
- Optionally expose a `shared_context` tool so downstream skills can read upstream results

## 🔗 Dependencies & Integration
- Imports from: `common.core.config`, `common.core.aliases`, `common.llm.base`, `common.llm.registry`
- Used by: `task-cli`, `skill-cli` — both import directly from `common.agent`
- Soft dep: `commands.task.command_registry.get_fastmarket_command_help` in `prompts.py` (graceful degradation if absent)
- External deps: none (LLM client resolved via `common.llm`)

## ✅ Do's
- Import from `common.agent` in task-cli and skill-cli
- Use `agent_call()` for simple programmatic invocations from other tools
- Keep `TaskLoop.run()` signature stable — callers depend on it
- Pass `shared_context=SharedContext(...)` to `TaskLoop` when skills must exchange data
- Pass `task_params` as a dict of `$SKILL_KEY` env vars exposed inside command execution

## ❌ Don'ts
- Do not add task-cli-specific logic here
- Do not hardcode allowed commands — always pass via `TaskConfig`
- Do not move `command_registry` to `common` — it runs subprocesses against fast-market CLIs and is task-cli-specific

## ⚠️ Pitfalls
- `prompts.py` lazy-imports `commands.task.command_registry.get_fastmarket_command_help`. If task-cli is not in `sys.path`, the import silently returns `None` and the function returns `None` — this is intentional graceful degradation, not a bug.
- `agent_call()` resolves provider from `skill` config first, then falls back to `task` config. If neither config exists, it raises `ConfigError`. Ensure at least one tool config is bootstrapped before calling.
- `doc.py` calls `--help` on each tool at runtime. Missing CLIs produce `None` rather than raising — tool docs are silently omitted.

## 🧪 Tests
- Test files: `tests/` (project root)
- Run with: `pytest tests/`
- Key scenarios covered: loop termination, alias resolution, tool call recording

## 🔍 Observability
- `verbose=True` on `TaskLoop` prints session header and tool results to stderr
- `debug="normal"` adds inner LLM dialog; `debug="full"` adds raw request/response dumps
- Key log markers: `shared_context_saved`, `provider_registered`, `alias_resolved`

## 🛠️ Extension Points
- To add a new built-in tool: define `build_*_tool() -> dict` (OpenAI function schema), add it to `tools` in `TaskLoop.run()`, handle it in `_handle_tool_calls()`
- To change prompt structure: edit `common/agent/prompts.py`
- To record LLM calls: wrap the provider with `common.llm.recorder.RecordingProvider`

## 📚 Related Documentation
- See `README.md` for usage, installation, and CLI reference
- See `task-cli/AGENTS.md` for task-cli-specific wiring
- See `skill-cli/AGENTS.md` for skill-cli-specific wiring
- See `common/llm/AGENTS.md` for provider configuration
