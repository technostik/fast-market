# task-agent

## Purpose
Agentic task execution CLI for fast-market. Executes whitelisted CLI commands iteratively with LLM-driven decision making.

## What it manages
- Task execution (CLI-driven agentic loop)
- Allowed commands whitelist
- Max iterations, timeouts, workdir

## What it does NOT manage
- LLM configuration → use `common-setup`

## Dependencies
- common.core.config (load_tool_config for task)
- common.llm.registry (discover_providers for LLM)
- common.core.paths
- common.cli.base
- No dependency on prompt-agent

## Do NOT
- Do not add LLM config management here
- Do not re-implement what common-setup does
