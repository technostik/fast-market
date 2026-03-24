# global-setup

## Purpose
Standalone CLI to configure LLM providers and global settings for all fast-market commands.

## What it manages
- LLM providers (add, remove, set-default) → `common/llm/config.yaml`
- Global default working directory → `common/config.yaml`

## What it does NOT manage
- Task-specific config (allowed commands, iterations) → use `prompt setup task`
- Prompt templates → use `prompt`
- Skills → use `skill`

## Key files
- `commands/setup/register.py` — all logic
- LLM config: `common/llm/config.yaml` (via common.core.config)
- Common config: `common/config.yaml` (via common.core.config)

## Dependencies
- common.core.config (load/save common and llm config)
- common.core.paths (config path resolution)
- NO dependency on any other agent

## Do NOT
- Do not manage per-tool config here
- Do not store API keys (only env var names)
- Do not require any other agent to be installed
