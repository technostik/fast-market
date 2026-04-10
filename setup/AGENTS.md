# common-setup

## Purpose
Standalone CLI to configure common settings and LLM providers for all fast-market commands.

## What it manages
- LLM providers (add, remove, set-default) → `~/.config/fast-market/common/llm/config.yaml`
- Common default working directory → `~/.config/fast-market/common/config.yaml`
- Clean working directory

## What it does NOT manage
- Task-specific config (allowed commands, iterations) → use `prompt setup task`
- Prompt templates → use `prompt`
- Skills → use `skill`

## Key files
- `commands/setup/register.py` — all logic
- LLM config: `~/.config/fast-market/common/llm/config.yaml` (via common.core.config)
- Common config: `~/.config/fast-market/common/config.yaml` (via common.core.config)

## Dependencies
- common.core.config (load/save common and llm config)
- common.core.paths (config path resolution)
- NO dependency on any other agent

## Commands
- `common-setup` — Run interactive wizard
- `common-setup --show` — Show current config
- `common-setup --show-path` — Show config file paths
- `common-setup workdir [path]` — Get or set workdir
- `common-setup clean-workdir` — Clean workdir files
- `common-setup llm list` — List providers
- `common-setup llm add <provider>` — Add provider
- `common-setup llm remove <provider>` — Remove provider
- `common-setup llm set-default <provider>` — Set default provider

## Do NOT
- Do not manage per-tool config here
- Do not store API keys (only env var names)
- Do not require any other agent to be installed
