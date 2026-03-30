# common/agent Module

## Purpose
Shared agentic loop for all fast-market CLI agents. Extracted from task-cli
so both task-cli and skill-cli can use it directly without subprocess.

## Public API

### session.py
- Session, Turn, ToolCallEvent — task session data model

### executor.py
- CommandResult — result of a single command execution
- execute_command(cmd_str, workdir, allowed, timeout) — execute whitelisted command
- resolve_and_execute_command(...) — same but with alias resolution

### prompts.py
- build_system_prompt(...) — build the LLM system prompt
- render_command_documentation(...) — render tool docs section
- TaskConfig-related defaults: DEFAULT_FASTMARKET_TOOLS, DEFAULT_SYSTEM_COMMANDS

### loop.py
- TaskConfig — configuration dataclass for the agentic loop
- TaskLoop — the agentic loop class
- run_dry_run(...) — dry run helper

## Soft dependency
common/agent/prompts.py has a lazy optional import of
commands.task.command_registry.get_fastmarket_command_help. If task-cli is
not in sys.path, the import fails silently and the function returns None
(graceful degradation). Do not move command_registry to common — it runs
subprocesses against fast-market CLIs and is task-cli-specific.

## Do's
- Import from common.agent in task-cli and skill-cli
- Keep TaskLoop.run() signature stable

## Don'ts
- Do not add task-cli-specific logic here
- Do not hardcode allowed commands — always pass via TaskConfig
