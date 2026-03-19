# prompt-agent

## 🎯 Purpose
Provide a unified CLI for managing reusable LLM prompt templates with pluggable providers, enabling consistent prompt execution with placeholder substitution across different LLM backends.

## 🏗️ Essential Components

- `cli/main.py` — CLI entry point that discovers and registers all commands
- `commands/apply/register.py` — Core execution engine with three input modes (saved/direct/stdin)
- `commands/task/register.py` — Agentic task execution with LLM-driven CLI loop
- `commands/alias/register.py` — Command alias management with description support
- `commands/setup/register.py` — Configuration wizard for provider, task prompts, and task management
- `core/substitution.py` — Placeholder resolution with file/stdin injection
- `core/models.py` — Domain models (Prompt, PromptExecution)
- `core/session.py` — Task session tracking and serialization
- `core/task_prompt.py` — Task prompt configuration (TaskPromptConfig)
- `common/core/aliases.py` — Alias resolution with caching and nested alias support
- `plugins/base.py` — Provider interfaces (LLMProvider, LazyLLMProvider)
- `storage/store.py` — SQLite persistence with PromptStore
- `plugins/anthropic/plugin.py` — Anthropic provider implementation
- `plugins/openai/plugin.py` — OpenAI provider implementation
- `plugins/openai_compatible/plugin.py` — Generic OpenAI-compatible endpoints
- `plugins/ollama/plugin.py` — Local Ollama provider

## 📋 Core Responsibilities

- Manage prompt templates (CRUD operations) with placeholders like `{var}`
- Execute prompts with three input modes (saved/direct/stdin)
- Resolve placeholders from CLI args, files (`@file`), or stdin (`-`)
- Dispatch to appropriate LLM provider with proper model/parameter overrides
- Record all executions for audit/telemetry
- Handle provider configuration through setup wizard or direct config editing
- Fail loudly with clear error messages for missing placeholders/files/providers

## 🔗 Dependencies & Integration

- Imports from: `common.core.config` (config loading), `common.core.registry` (plugin discovery), `common.cli.helpers` (output formatting), `common.storage` (base storage)
- Used by: End users via CLI, potential API layer in future
- External deps: `click` (CLI), `pyyaml` (config), `sqlalchemy`+`alembic` (storage), `anthropic`, `openai` (optional)

## ✅ Do's

- **Use common infrastructure** — Reuse `common.core.config`, `common.cli.helpers`, `common.storage` instead of reinventing
- **Fail loudly** — Validate all inputs: missing placeholders → ValueError with list, missing files → FileNotFoundError with path, missing provider → exit with setup instructions
- **Support three input modes** — Saved prompts (DB), direct strings (inline), stdin (piping)
- **Resolve placeholders consistently** — `key=value` (literal), `key=-` (stdin), `key=@file` (file)
- **Record all executions** — Store prompt name (or `<direct>`/`<stdin>`), input args, resolved content, output, model, timestamp
- **Use lazy provider initialization** — Only load provider SDKs when first used, handle missing env vars gracefully
- **Make configuration XDG-compliant** — `~/.config/`, `~/.local/share/`, `~/.cache/`

## ❌ Don'ts

- **Don't hardcode provider logic** — All providers must implement `LLMProvider` interface
- **Don't swallow errors** — No silent failures for missing API keys, missing files, or missing placeholders
- **Don't store API keys in config** — Use environment variables referenced via `api_key_env`
- **Don't duplicate registry logic** — Use `common.core.registry.discover_commands`/`discover_plugins`
- **Don't assume tty** — Support non-interactive usage with `--yes` flags and proper stdin handling
- **Don't bypass PromptStore** — All persistence must go through the store abstraction

## 🛠️ Extension Points

**To add a new provider:**
1. Create `plugins/newprovider/` with `plugin.py` and `register.py`
2. Implement class extending `LazyLLMProvider`
3. Add `_initialize()` that creates a real provider instance
4. Implement `complete()` and `list_models()`
5. Add to `_SUPPORTED_PROVIDERS` in `commands/setup/register.py`

**To add a new command:**
1. Create `commands/newcmd/register.py`
2. Define click command with appropriate arguments/options
3. Return `CommandManifest(name="newcmd", click_command=cmd)`
4. Command auto-discovered via registry

**To modify placeholder resolution:**
- Extend `resolve_arguments()` in `core/substitution.py`
- Keep injection patterns (`@file`, `-`) consistent

**To add a command to task whitelist:**
1. Add to `_DEFAULT_ALLOWED` in `commands/task/executor.py`, or
2. Use `prompt setup --add-task-command <name>`

**To add command aliases:**
1. Create/edit `~/.config/prompt-agent/aliases.yaml`
2. Add entries under `aliases:` key
3. Or use `prompt alias <name> "<command>"` CLI
4. Include optional `description` field for better documentation
5. Aliases are automatically documented in task system prompts

**To manage task prompts:**
1. Use `prompt setup --list-task-prompts` to see available prompts
2. Use `prompt setup --set-task-prompt <name>` to activate a prompt
3. Use `prompt setup --edit-task-prompt <name>` to customize a prompt
4. Use `prompt setup --import-task-prompt <file>` to import from YAML
5. Use `prompt setup --show-task-tools` to preview the inner tool documentation
6. Task prompts are stored in `~/.local/share/fast-market/task_prompts/`

**To manage tools doc prompts:**
1. Use `prompt setup --list-tools-doc-prompts` to see available prompts
2. Use `prompt setup --set-tools-doc-prompt <name>` to activate a prompt
3. Use `prompt setup --show-tools-doc-prompt <name>` to view a prompt template
4. Use `prompt setup --edit-tools-doc-prompt <name>` to customize a prompt
5. Use `prompt setup --import-tools-doc-prompt <file>` to import from YAML
6. Tools doc prompts are stored in `~/.local/share/fast-market/tools_doc_prompts/`
7. Default template uses placeholders: `{aliases}`, `{fastmarket_tools}`, `{system_commands}`, `{other_commands}`

## 📚 Related Documentation

- See `AGENTS.md` in root for project-wide golden rules (DRY, KISS, CODE IS LAW, FAIL LOUDLY)
- Refer to provider-specific READMEs in `plugins/` for implementation details
- Check `CHANGELOG.md` for test scenarios and edge cases
- See `alembic.ini` for database migration setup
- See `TASK.md` for `prompt task` command usage examples
