# Fast Market

A modular CLI toolkit for web creators to automate content marketing, monitoring, and AI-assisted workflows.

## Overview

Fast Market provides a collection of pluggable CLI tools that help you:
- **Manage content corpus** — Index and search content from YouTube, Obsidian
- **Monitor sources** — Watch YouTube channels, RSS feeds, and search keywords for new content
- **Generate images** — AI-powered image generation with FLUX.2
- **Send messages** — Alert and interact via Telegram
- **Execute prompts** — Reusable LLM prompt templates with multiple providers
- **Run agentic tasks** — LLM-driven iterative CLI execution
- **Manage skills** — Reusable skill scripts with learning capabilities

## Architecture

```
fast-market/
├── common/                    # Shared utilities
│   ├── cli/                   # CLI helpers, base classes
│   ├── core/                  # Config, paths, registry
│   ├── auth/                  # Authentication (YouTube, Telegram)
│   ├── storage/               # SQLite + SQLAlchemy base
│   ├── llm/                   # LLM providers (Anthropic, OpenAI, Ollama, Groq, xAI)
│   └── learn/                 # LLM learning utilities
│
├── corpus-cli/                # Content indexing and search
├── monitor-cli/               # Rule-based source monitoring
├── youtube-cli/               # YouTube Data API operations
├── image-cli/                 # AI image generation
├── message-cli/               # Messaging (Telegram)
├── prompt-cli/                # LLM prompt management
├── task-cli/                  # Agentic task execution
├── skill-cli/                 # Skill management
├── tiktok-cli/                # TikTok operations
└── setup/                     # Common configuration
```

All tools use:
- **XDG-compliant paths**: Config in `~/.config/fast-market/`, data in `~/.local/share/fast-market/`
- **Plugin architecture**: Auto-discovery of commands and source plugins
- **SQLite storage**: Local persistence without external dependencies

## Installation

Install all tools:

```bash
pip install -e './corpus-cli[ml,youtube]'
pip install -e './monitor-cli[youtube]'
pip install -e './youtube-cli'
pip install -e './image-cli'
pip install -e './message-cli'
pip install -e './prompt-cli[openai]'
pip install -e './task-cli'
pip install -e './skill-cli'
pip install -e './tiktok-cli'
pip install -e './setup'
```

Or install everything at once:

```bash
pip install -e './corpus-cli[ml,youtube]' \
               -e './monitor-cli[youtube]' \
               -e './youtube-cli' \
               -e './image-cli' \
               -e './message-cli' \
               -e './prompt-cli[openai]' \
               -e './task-cli' \
               -e './skill-cli' \
               -e './tiktok-cli' \
               -e './setup'
```

### Optional Dependency Groups

| Group | Tools | Description |
|-------|-------|-------------|
| `ml` | corpus-cli | Sentence transformers for embeddings |
| `youtube` | corpus-cli, monitor-cli | YouTube API support |
| `whisper` | corpus-cli | YouTube transcription |
| `openai` | prompt-cli | OpenAI provider support |
| `dev` | All | Development testing tools |

## Configuration

### First-time Setup

Run the common setup wizard to configure LLM providers:

```bash
common-setup
```

This configures:
- Default LLM provider (Anthropic, OpenAI, Ollama, Groq, xAI)
- Default working directory
- API keys via environment variables

### LLM Provider Configuration

Add providers with:

```bash
common-setup llm add anthropic
common-setup llm add openai
common-setup llm add ollama
common-setup llm add groq
common-setup llm add xai
```

Set default:

```bash
common-setup llm set-default anthropic
```

### Environment Variables

Most tools require API keys set as environment variables:

```bash
# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI
export OPENAI_API_KEY="sk-..."

# Telegram (for message-cli)
export TELEGRAM_BOT_TOKEN="..."

# YouTube (for youtube-cli, corpus-cli)
export YOUTUBE_API_KEY="..."

# Groq
export GROQ_API_KEY="..."

# xAI
export XAI_API_KEY="..."
```

## CLI Reference

### corpus — Content Indexing & Search

Index and search content from multiple sources with embeddings.

```bash
# Setup
corpus setup run              # Run interactive setup wizard
corpus setup edit             # Edit config.yaml

# Sync content
corpus sync                   # Sync new items (default)
corpus sync --mode backfill  # Re-fetch all content
corpus sync --mode reindex   # Regenerate embeddings

# Search
corpus search "query"         # Search indexed content
corpus list                   # List all documents
corpus status                 # Show corpus statistics

# Serve
corpus serve                  # Start web UI
corpus embed-server           # Start embedding server
```

---

### monitor — Rule-Based Monitoring

Watch sources and trigger actions based on rules.

```bash
# Setup sources
monitor setup source-add --plugin youtube --identifier UC...
monitor setup source-add --plugin rss --identifier https://...
monitor setup source-add --plugin yt-search --identifier "AI tutorial"

# Setup actions
monitor setup action-add --id notify --command 'echo "$ITEM_TITLE"'

# Setup rules
monitor setup rule-add --id tech-videos \
  --conditions "source_plugin == 'youtube' and content_type == 'video'" \
  --action-ids notify

# Run monitoring
monitor run                   # Normal mode
monitor run --force --dry-run # Test mode
monitor run --cron            # Cron mode

# View logs
monitor logs --since 1d
monitor status
```

---

### youtube — YouTube Operations

Search, comments, and replies via YouTube Data API.

```bash
youtube search "query"
youtube comments --video-id <id>
youtube reply --comment-id <id> --text "Reply text"
```

---

### image — AI Image Generation

Generate images with FLUX.2 and other engines.

```bash
# Generate
image generate "A sunset over mountains"
image generate "Portrait" -s portrait -S 8

# Setup
image setup                   # Interactive wizard
image setup -a flux2          # Add engine

# Serve API
image serve -p 8080
```

---

### message — Messaging

Send alerts and receive responses via Telegram.

```bash
# Setup
message setup                 # Configure Telegram bot

# Send alert
message alert "Hello world"

# Ask and wait for reply
message ask "What is your name?"
```

---

### prompt — LLM Prompt Management

Manage and execute reusable LLM prompts.

```bash
# CRUD
prompt create my-prompt --template "..."
prompt list
prompt get my-prompt
prompt update my-prompt --edit
prompt delete my-prompt

# Execute
prompt apply my-prompt var1=value1
prompt apply --direct "Your prompt here" var=value
echo "input" | prompt apply --stdin

# Task execution
prompt task "Build a website"
```

---

### task — Agentic Task Execution

Execute whitelisted CLI commands iteratively with LLM.

```bash
task "Install nginx and configure firewall"
task "Deploy to production" --max-iterations 5
```

---

### skill — Skill Management

Manage reusable skills with learning capabilities.

```bash
skill list
skill create my-skill
skill show my-skill
skill run my-skill --input "..."
skill apply my-skill/script.sh arg1
skill delete my-skill
```

---

### common-setup — Common Configuration

Configure shared settings across all tools.

```bash
common-setup                  # Interactive wizard
common-setup --show          # Show current config
common-setup workdir [path]  # Get/set workdir
common-setup llm list        # List providers
common-setup llm add anthropic
common-setup llm set-default anthropic
```

---

## Features

### Plugin Architecture

Each CLI tool supports plugins that can:
- Add new source types (YouTube, RSS, Obsidian)
- Inject CLI options dynamically
- Provide API routers
- Add frontend components

### Incremental Sync

Tools like `corpus sync` and `monitor run` support incremental updates:
- Cursor-based tracking (ID or date)
- Avoid re-processing already-seen content
- Force mode for testing

### XDG Compliance

All configuration and data follows XDG spec:
- Config: `~/.config/fast-market/`
- Data: `~/.local/share/fast-market/`
- Cache: `~/.cache/fast-market/`

### Multiple Output Formats

Most commands support `--format` for output:

```bash
--format json   # JSON output
--format yaml   # YAML output  
--format text   # Human-readable (default)
```

### Piping Support

Commands that accept IDs can read from stdin:

```bash
corpus search "query" --format json | jq '.[0].id' | corpus get-from-id
```

## Development

### Running Tests

```bash
# All tests
pytest

# Specific tool
cd corpus-cli && pytest

# With coverage
pytest --cov=. --cov-report=html
```

### Adding New Plugins

1. Create `plugins/your_plugin/` directory
2. Implement plugin class extending base (SourcePlugin, ImageEnginePlugin, etc.)
3. Add `register.py` returning `PluginManifest`
4. Plugin auto-discovers on startup

### Adding New Commands

1. Create `commands/your_command/` directory
2. Implement `register(plugin_manifests)` returning `CommandManifest`
3. Command auto-discovers on startup

See individual tool AGENTS.md files for detailed development guidelines.

## License

MIT
