# prompt-agent

CLI tool for managing reusable LLM prompt templates with parameter substitution and pluggable providers (Anthropic, OpenAI, OpenAI-compatible, Ollama).

## Installation

```bash
# Install from source
pip install -e .

# Install with all providers
pip install -e ".[openai]"  # OpenAI and OpenAI-compatible providers
# Anthropic is included by default
# Ollama requires no additional deps (uses urllib)
```

### Optional Dependencies
- `openai` — OpenAI and OpenAI-compatible providers
- `dev` — Development tools (pytest)

## Configuration

Configuration follows XDG specs:
- **Config**: `~/.config/prompt-agent/config.yaml`
- **Data**: `~/.local/share/prompt-agent/prompts.db`
- **Cache**: `~/.cache/prompt-agent/`

### Configuration File Example

```yaml
default_provider: anthropic
providers:
  anthropic:
    default_model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
  openai:
    default_model: gpt-4
    api_key_env: OPENAI_API_KEY
  openai-compatible:
    default_model: gpt-4o-mini
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_COMPATIBLE_API_KEY
  ollama:
    default_model: llama3.2
    base_url: http://127.0.0.1:11434
```

### First-time Setup

Run the interactive setup wizard:

```bash
prompt setup
```

This will guide you through:
- Selecting providers
- Configuring default models
- Setting base URLs (for OpenAI-compatible and Ollama)
- Recording required environment variables

### Environment Variables

Set API keys in your shell profile:

```bash
# Anthropic
export ANTHROPIC_API_KEY="sk-..."

# OpenAI
export OPENAI_API_KEY="sk-..."

# OpenAI-compatible (if different)
export OPENAI_COMPATIBLE_API_KEY="sk-..."
```

## CLI Reference

### Global Flags
All commands support:
- `--format text|json` — Output format (default: text)

---

### `prompt create`

Create a new prompt template with parameters like `{parameter}`.

```bash
# Create from inline content
prompt create summarize --content "Summarize this: {text}" --description "Summarization prompt"

# Create from file
prompt create translate --from-file templates/translate.txt --provider openai --model gpt-4

# With default model settings
prompt create code-review --content "Review this code: {code}" --temperature 0.3 --max-tokens 4000
```

**Options:**
| Option | Description | Default |
|--------|-------------|---------|
| `--content` | Prompt template content | |
| `--from-file` | Load content from file | |
| `--description` | Prompt description | "" |
| `--provider` | Default provider | "" |
| `--model` | Default model | "" |
| `--temperature` | Temperature (0-2) | 0.7 |
| `--max-tokens` | Max tokens in response | 2048 |

---

### `prompt list`

List all saved prompts.

```bash
prompt list
prompt list --format json | jq '.[].name'
```

**Output (text):**
```
summarize
  Description: Summarization prompt
  Provider: anthropic
  Model: claude-sonnet-4-20250514

translate
  Description: Translation prompt
  Provider: openai
  Model: gpt-4
```

---

### `prompt get`

Show a stored prompt with its parameters.

```bash
prompt get summarize
prompt get translate --format json
```

**Output (text):**
```
summarize
Description: Summarization prompt
Parameters: text
Provider: anthropic
Model: claude-sonnet-4-20250514

---
Summarize this: {text}
```

---

### `prompt update`

Update an existing prompt.

```bash
# Update content
prompt update summarize --content "New template with {text} and {style}"

# Update from file
prompt update translate --from-file new-translate.txt

# Update metadata only
prompt update code-review --provider openai --model gpt-4-turbo --temperature 0.2
```

**Options:** Same as `create` (all optional)

---

### `prompt delete`

Delete a prompt.

```bash
prompt delete old-prompt
prompt delete unused-prompt --yes  # Skip confirmation
```

---

### `prompt apply` — **Main Command**

Apply a prompt with parameter substitution. Supports three input modes.

#### Mode 1: Saved Prompt (Database Lookup)

```bash
# Basic usage with parameters
prompt apply summarize text=@article.txt

# Override provider/model
prompt apply translate text="Hello world" target=fr --provider openai --model gpt-4

# JSON output for scripting
prompt apply code-review code=@script.py --format json | jq '.output'
```

#### Mode 2: Direct Prompt (Inline String)

```bash
# Use a literal string as prompt
prompt apply "Explain {topic} in simple terms" topic="quantum physics"

# Multiple parameters
prompt apply "Translate from {source} to {target}: {text}" source=en target=es text="Hello world"
```

#### Mode 3: Stdin Mode (Piping/Chaining)

```bash
# Read prompt from stdin
echo "What is the capital of {country}?" | prompt apply - country=France

# Pipe content through
cat template.txt | prompt apply --stdin var=value

# Chain commands
echo "Summarize: {text}" | prompt apply - text=@long-article.txt | prompt apply "Translate to Spanish: {text}" text=-
```

**Parameter Resolution:**
- `key=value` — Literal substitution
- `key=-` — Read from stdin
- `key=@file.txt` — Read from file
- `@filename` — Inline file reference (resolved relative to workdir)

**Options:**
| Option | Description |
|--------|-------------|
| `--provider` | Override provider |
| `--model` | Override model |
| `--temperature` | Override temperature |
| `--max-tokens` | Override max tokens |
| `--stdin` | Read prompt from stdin |
| `--workdir` | Working directory for @filename resolution |

**Error Handling (Fails Loudly):**
- Missing parameter → `ValueError` with list of missing args
- Missing file → `FileNotFoundError` with path
- Missing provider → Exit with setup instructions
- No stdin when expected → Clear error message

---

### `prompt providers`

List configured LLM providers.

```bash
prompt providers
prompt providers --format json | jq '.[] | select(.configured) | .name'
```

**Output (text):**
```
anthropic (default): configured
  Default model: claude-sonnet-4-20250514
openai: configured
  Default model: gpt-4
ollama: not configured
```

---

### `prompt setup`

Configuration wizard and provider management.

```bash
# Interactive wizard
prompt setup

# Show current config
prompt setup --show-config
# or: prompt setup -c

# Show config file path
prompt setup --config-path
# or: prompt setup -p

# Show task tools documentation
prompt setup --show-task-tools
# or: prompt setup -t
```

#### Provider Management

```bash
# List configured providers
prompt setup providers list

# Add a provider (interactive)
prompt setup providers add openai

# Remove a provider
prompt setup providers remove ollama

# Set default provider
prompt setup providers set-default anthropic
```

#### Task Prompt Management

Manage custom task prompts that control the LLM's behavior in `prompt task`:

```bash
# List available task prompts
prompt setup task-prompts list

# Set active task prompt
prompt setup task-prompts set my-custom-prompt

# Reset to built-in default prompt
prompt setup task-prompts set default

# Show a specific prompt's content
prompt setup task-prompts show my-custom-prompt

# Edit a prompt in your default editor
prompt setup task-prompts edit my-custom-prompt

# Import a prompt from YAML file
prompt setup task-prompts import ./my-prompt.yaml
```

**Prompt YAML format:**
```yaml
name: my-custom-prompt
description: Custom task prompt for specific use case
template: |
  Your custom system prompt template here.
  Supports multi-line content.
```

#### Task Configuration

```bash
# List task configuration
prompt setup task-commands list

# Add a command to task whitelist
prompt setup task-commands add python3

# Remove a command from task whitelist
prompt setup task-commands remove rm

# Set max iterations for task
prompt setup task set-max-iterations 50

# Set default timeout (seconds)
prompt setup task set-timeout 120
```

---

### `prompt alias`

Manage command aliases for `prompt task`. Aliases are shortcuts that resolve to actual commands, making it easier to type frequently used command combinations.

**Configuration file:** `~/.config/prompt-agent/aliases.yaml` (XDG compliant)

```bash
# List all aliases
prompt alias
prompt alias --list

# Show specific alias
prompt alias alert-me

# Create/update alias
prompt alias alert-me "message alert"
prompt alias ls-files "ls -la"

# Create alias with description (shown in task prompts)
prompt alias alert-me "message alert" -d "Send an alert message"

# Remove alias
prompt alias alert-me --remove

# Show config file path
prompt alias --config-path

# Export aliases to file
prompt alias --export > backup.yaml

# Import aliases from file
prompt alias --file team_aliases.yaml

# JSON/YAML output for scripting
prompt alias --list --format json
prompt alias --list --format yaml
```

**Alias Resolution:**
- Aliases work with `prompt task` — the LLM sees aliases in documentation
- Arguments are passed through to the resolved command
- Nested aliases (alias → alias → command) are supported (max depth 5)
- Alias resolution is logged in debug mode

**Example aliases file (with descriptions):**
```yaml
aliases:
  alert-me:
    command: message alert
    description: Send an alert message
  search-youtube: youtube search
  img-gen: image generate
  summarize-prompt: prompt apply summarize
  ls-files: ls -la
```

**Example usage:**
```bash
# Create alias with description
prompt alias alert-me "message alert" -d "Send an alert message"

# Use in task - LLM sees the alias and can use it directly
prompt task "alert-me 'server is down'" --workdir ./server

# Dry-run shows alias resolution
prompt task "alert-me 'hello'" --dry-run
# [DRY RUN] Available aliases:
#   - alert-me → message alert
```

## Features

### Command Aliases
Create shortcuts for frequently used commands in `prompt task`:
```bash
prompt alias alert-me "message alert"
prompt alias img-gen "image generate"
```
Aliases are automatically documented in task system prompts, so the LLM knows available shortcuts.

Aliases can include descriptions for better documentation:
```bash
prompt alias alert-me "message alert" -d "Send an alert message"
```

### Task Sessions
The `prompt task` command tracks and displays session information:
```bash
# Normal output shows session header with task details
prompt task "analyze data"

# Output:
# ============================================================
# TASK SESSION: analyze data
# Provider: anthropic, Model: claude-sonnet-4-20250514
# Workdir: /path/to/current/dir
# ============================================================

# Suppress session output
prompt task "quick task" --silent

# Save session to YAML file for later review
prompt task "complex task" --save-session session.yaml

# Debug mode shows full session YAML
prompt task "debug task" --debug full
```

Session information includes:
- Task description
- Provider and model used
- Working directory
- Parameters (if any)
- All turns, tool calls, and results

### Three Input Modes
1. **Saved prompts** — Reusable templates with stored settings
2. **Direct prompts** — Ad-hoc strings for quick tasks
3. **Stdin mode** — Enable command chaining and piping

### Placeholder Resolution
- File injection with `@file.txt`
- Stdin injection with `-`
- Automatic extraction for validation

### Provider Fallback Chain
CLI option > Saved prompt > Default provider

### Execution Recording
All executions are recorded with:
- Prompt name (or `<direct>`/`<stdin>`)
- Input arguments
- Resolved content
- Output
- Model used
- Timestamp
- Usage metadata

## Architecture

```
prompt-agent/
├── cli/                 # CLI entry point
│   ├── main.py          # Command registration
│   └── commands/        # Individual commands
│       ├── apply/       # Main execution logic
│       ├── create/      # Prompt creation
│       ├── get/          # Prompt retrieval
│       ├── list/        # Listing
│       ├── update/      # Updates
│       ├── delete/      # Deletion
│       ├── alias/       # Alias management
│       ├── providers/    # Provider listing
│       └── setup/       # Configuration wizard
├── core/                # Core domain models
│   ├── models.py        # Prompt, Execution
│   └── substitution.py  # Placeholder resolution
├── common/              # Shared infrastructure
│   └── core/
│       └── aliases.py   # Alias resolution
├── plugins/             # LLM providers
│   ├── base.py          # Provider interfaces
│   ├── anthropic/       # Anthropic provider
│   ├── openai/          # OpenAI provider
│   ├── openai_compatible/ # Custom endpoints
│   └── ollama/          # Local Ollama
├── storage/             # Persistence
│   ├── store.py         # PromptStore interface
│   └── migrations/      # Alembic DB migrations
└── tests/               # Test suite
    └── test_aliases.py  # Alias tests
```

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/
```

### Adding a New Provider

1. Create plugin directory: `plugins/newprovider/`
2. Implement provider class extending `LazyLLMProvider`
3. Add `register()` function returning `PluginManifest`
4. Update `pyproject.toml` with new package
5. Add to `_SUPPORTED_PROVIDERS` in `setup.py`

Example provider structure:
```python
from plugins.base import LLMProvider, LazyLLMProvider, LLMRequest, LLMResponse

class NewProvider(LazyLLMProvider):
    name = "newprovider"
    
    def _initialize(self):
        # Lazy initialization
        self._provider = _RealNewProvider(...)
    
def register(config: dict) -> PluginManifest:
    return PluginManifest(name="newprovider", provider_class=NewProvider)
```

### Adding a New Command

1. Create `commands/newcmd/register.py` with `register()` function
2. Return `CommandManifest` with click command
3. Command automatically discovered via plugin registry

**Example command structure:**
```python
from commands.base import CommandManifest

def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("newcmd")
    @click.argument("name")
    def newcmd_cmd(name):
        """Command description."""
        click.echo(f"Hello {name}")
    
    return CommandManifest(name="newcmd", click_command=newcmd_cmd)
```

### Adding Command Aliases

Aliases are defined in `~/.config/prompt-agent/aliases.yaml` or managed via CLI:

```yaml
aliases:
  alert-me: message alert
  img-gen: image generate
```

The alias system is implemented in `common/core/aliases.py`:
- `load_aliases()` — Load from YAML with caching
- `resolve_alias(cmd_str)` — Replace alias with actual command
- `get_reverse_aliases()` — Map commands to their aliases (for docs)
