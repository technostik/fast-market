# task-agent

## Purpose
Agentic task execution CLI for fast-market. Executes whitelisted CLI commands iteratively with LLM-driven decision making.

The agentic loop (TaskLoop, TaskConfig, executor, prompts, session) lives in
common/agent/. task-cli re-exports these via thin shims. task-cli owns only:
- CLI wiring (register.py, task_entry)
- commands/task/command_registry.py (help extraction from fast-market CLIs)
- commands/setup/ (task-specific config management)

## What it manages
- Task execution (CLI-driven agentic loop)
- Allowed commands whitelist
- Max iterations, timeouts, workdir

## What it does NOT manage
- LLM configuration → use `toolsetup`

## Dependencies
- common.core.config (load_tool_config for task)
- common.llm.registry (discover_providers for LLM)
- common.core.paths
- common.cli.base
- No dependency on prompt-agent

## Do NOT
- Do not add LLM config management here
- Do not re-implement what toolsetup does
