# Fast Market

A modular CLI toolkit for web creators to automate content marketing, monitoring, and AI-assisted workflows.

## Overview

Fast Market provides a collection of pluggable CLI tools that help you:
- **Manage content corpus** — Index and search content from YouTube, Obsidian
- **Monitor sources** — Watch YouTube channels, RSS feeds, and search keywords for new content
- **Generate images** — AI-powered image generation with FLUX.2
- **Generate sound** — Text-to-speech and music generation with Kokoro, Qwen3-TTS, MusicGen
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
 ├── sound-cli/                 # TTS and music generation
 ├── message-cli/               # Messaging (Telegram)
 ├── prompt-cli/                # LLM prompt management
 ├── task-cli/                  # Agentic task execution
 ├── skill-cli/                # Skill management
 └── toolsetup-cli/             # Tool configuration
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
pip install -e './sound-cli[kokoro]'
pip install -e './message-cli'
pip install -e './prompt-cli[openai]'
pip install -e './task-cli'
  pip install -e './skill-cli'
  pip install -e './toolsetup-cli'
```

Or install everything at once:

```bash
pip install -e './corpus-cli[ml,youtube]' \
               -e './monitor-cli[youtube]' \
               -e './youtube-cli' \
               -e './image-cli' \
               -e './sound-cli[kokoro]' \
               -e './message-cli' \
               -e './prompt-cli[openai]' \
               -e './task-cli' \
                -e './skill-cli' \
                -e './toolsetup-cli'
```

### Optional Dependency Groups

| Group | Tools | Description |
|-------|-------|-------------|
| `ml` | corpus-cli | Sentence transformers for embeddings |
| `youtube` | corpus-cli, monitor-cli | YouTube API support |
| `whisper` | corpus-cli | YouTube transcription |
| `openai` | prompt-cli | OpenAI provider support |
| `kokoro` | sound-cli | Kokoro TTS engine |
| `qwen3` | sound-cli | Qwen3-TTS voice design engine |
| `musicgen` | sound-cli | MusicGen music generation |
| `dev` | All | Development testing tools |

## Configuration

### Profiles (personas)

All tools run under an active **profile**, so you can manage several personas
(different YouTube/Substack/Twitter/Telegram accounts, free-service API keys,
prompts, skills, browser sessions and corpus data) from one installation. Each
profile is fully isolated under `~/.config|.local/share|.cache/fast-market/profiles/<name>/`.

A reserved `_shared` base layer is inherited by every profile (deep-merged,
profile wins) — put things common to all personas there (e.g. the Anthropic key,
the working directory, shared prompts/skills/browser scripts). Resources present
in both the profile and `_shared` resolve to the profile's copy; lists tag the
shared-only ones `(shared)`.

```bash
toolsetup profile list                 # list profiles, '*' marks the active one
toolsetup profile show-shared          # show the _shared base
toolsetup profile show-path [name]     # print resolved config/data/cache paths
toolsetup profile create <name>        # new empty profile
toolsetup profile clone <src> <dst>    # copy a profile (config + data + cache)
toolsetup profile use <name>           # switch the active profile
toolsetup profile delete <name>        # remove a profile
toolsetup profile migrate              # move a legacy (pre-profile) layout into 'joriel'
```

Select the active profile by (first match wins): the global `--profile/-P` flag
on any command, the `FASTMARKET_PROFILE` env var, the `active_profile` pointer
file (set by `profile use`), else `default`.

```bash
youtube --profile alice get-last       # one-off override
export FASTMARKET_PROFILE=alice        # whole shell
```

Secrets are stored inline in each profile's `config.yaml` (resolved before any
`api_key_env` fallback), so free-service keys differ per persona while a shared
key can live once in `_shared`.

### First-time Setup

Run the toolsetup wizard to configure LLM providers:

```bash
toolsetup
```

This configures:
- Default LLM provider (Anthropic, OpenAI, Ollama, Groq, xAI)
- Default working directory
- API keys via environment variables

### LLM Provider Configuration

Add providers with:

```bash
toolsetup llm add anthropic
toolsetup llm add openai
toolsetup llm add ollama
toolsetup llm add groq
toolsetup llm add xai
```

Set default:

```bash
toolsetup llm set-default anthropic
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
monitor setup source-add --plugin directory --identifier /path/to/watch

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

# Timeout control (when monitor run is blocked on a long action)
monitor wait                  # Extend deadline by +5min (configured by timeout.increment)
monitor stop                  # Abort the current run immediately

# View logs
monitor logs --since 1d
monitor status
```

**Monitor run timeout** is configured in `~/.config/fast-market/monitor/config.yaml`:

```yaml
timeout:
  alert_after: 15m     # Send alert_cmd when elapsed time exceeds this
  max: 30m             # Kill action and exit at this hard limit
  increment: 5m        # How much time 'monitor wait' adds
  alert_cmd: "message alert 'monitor run: {elapsed}min elapsed — run `monitor wait` or `monitor stop`'"
```

When `alert_after` is reached, `alert_cmd` fires (typically a Telegram message). The user can run `monitor wait` to extend the deadline or `monitor stop` to abort.

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

### sound — Sound Generation

Generate speech and music from text using AI engines.

```bash
# Text-to-Speech
sound speak "Hello world"                                      # Kokoro with default voice
sound speak "Bonjour" -e qwen3 --voice "A soft French voice" -L French   # Qwen3 voice design
sound speak "Hi" --voice "am_michael" --speed 1.5              # Kokoro voice override

# Music Generation
sound music "lofi piano beat"
sound music "upbeat electronic" -d 10                           # Custom duration

# Setup
sound setup -c                                                  # Show current config
sound setup -p                                                  # Show config file path
sound setup path                                                # Show workdir
sound setup path ~/my-output                                    # Set workdir
sound setup edit                                                # Edit config in editor
sound setup reset                                               # Reset to defaults
```

**Available engines:**
- `kokoro` — Lightweight TTS with weighted voice mixing (`am_michael*0.7,am_fenrir*0.3`)
- `qwen3` — Voice design via natural language descriptions (GPU recommended)
- `musicgen` — Text-to-music generation (GPU recommended)

**Config location:** `~/.config/fast-market/sound/config.yaml`

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
prompt apply my-prompt --timeout 300    # override LLM call timeout (seconds)

# Batch execution
prompt batch-apply -n my-prompt -i field -o result -f data.json -O out.json
prompt batch-apply -n my-prompt -i field -o result -f data.json --timeout 0  # no timeout

# Task execution
prompt task "Build a website"
```

**LLM call timeouts** are configured in `~/.config/fast-market/common/agent/config.yaml`:

```yaml
llm_call_warn: 180     # Print warning to stderr if call exceeds this (seconds)
llm_call_timeout: 600  # Hard HTTP timeout per LLM call (seconds, 0 = no limit)
```

Override per-invocation with `--timeout <seconds>` (0 = no limit).

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
skill run "Accomplish task X"          # LLM-orchestrated multi-skill run
skill run "task" --timeout 1800        # Override per-skill timeout (seconds, 0 = no limit)
skill apply my-skill KEY=VALUE         # Apply single skill
skill apply my-skill/script.sh arg1
skill delete my-skill
```

**Skill execution timeouts** default to 15 minutes (900s) per skill step. Override globally in
`~/.config/fast-market/common/agent/config.yaml` (`default_timeout`), per-skill in `SKILL.md`
frontmatter (`timeout: <seconds>`), or per-invocation with `--timeout`.

---

### toolsetup — Tool Configuration

Configure shared settings across all tools.

```bash
toolsetup                  # Interactive wizard
toolsetup --show          # Show current config
toolsetup workdir [path]  # Get/set workdir
toolsetup llm list        # List providers
toolsetup llm add anthropic
toolsetup llm set-default anthropic
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
