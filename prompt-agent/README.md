# prompt-agent

CLI tool for managing reusable LLM prompt templates with placeholder substitution and pluggable providers (Anthropic, OpenAI, OpenAI-compatible, Ollama).

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

Create a new prompt template with placeholders like `{placeholder}`.

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

Show a stored prompt with its placeholders.

```bash
prompt get summarize
prompt get translate --format json
```

**Output (text):**
```
summarize
Description: Summarization prompt
Placeholders: text
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

Apply a prompt with placeholder substitution. Supports three input modes.

#### Mode 1: Saved Prompt (Database Lookup)

```bash
# Basic usage with placeholders
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

# Multiple placeholders
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

**Placeholder Resolution:**
- `key=value` — Literal substitution
- `key=-` — Read from stdin
- `key=@file.txt` — Read from file

**Options:**
| Option | Description |
|--------|-------------|
| `--provider` | Override provider |
| `--model` | Override model |
| `--temperature` | Override temperature |
| `--max-tokens` | Override max tokens |
| `--stdin` | Read prompt from stdin |

**Error Handling (Fails Loudly):**
- Missing placeholder → `ValueError` with list of missing args
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

# List configured providers
prompt setup --list-providers

# Add a provider non-interactively
prompt setup --add-provider openai

# Remove a provider
prompt setup --remove-provider ollama

# Set default provider
prompt setup --set-default anthropic

# Show current config
prompt setup --show-config

# Show config file path
prompt setup --config-path
```

## Features

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
│       ├── apply.py     # Main execution logic
│       ├── create.py    # Prompt creation
│       ├── get.py       # Prompt retrieval
│       ├── list.py      # Listing
│       ├── update.py    # Updates
│       ├── delete.py    # Deletion
│       ├── providers.py # Provider listing
│       └── setup.py     # Configuration wizard
├── core/                # Core domain models
│   ├── models.py        # Prompt, Execution
│   └── substitution.py  # Placeholder resolution
├── plugins/             # LLM providers
│   ├── base.py          # Provider interfaces
│   ├── anthropic/       # Anthropic provider
│   ├── openai/          # OpenAI provider
│   ├── openai_compatible/ # Custom endpoints
│   └── ollama/          # Local Ollama
├── storage/             # Persistence
│   ├── store.py         # PromptStore interface
│   └── migrations/      # Alembic DB migrations
└── common/              # Shared infrastructure
    ├── core/            # Config, registry
    ├── cli/             # CLI helpers
    └── storage/         # Base storage classes
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
