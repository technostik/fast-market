# Fast-Market Multi-Agent System: Implementation Summary

## Quick Overview

This document outlines the plan to:
1. **Refactor `corpus-agent`** to extract shared infrastructure into `/common`
2. **Build `prompt-agent`** as a new tool using the shared foundation
3. **Enable seamless cooperation** between agents via bash pipes and shared data

## File Organization

```
/mnt/project/
├── REFACTORING_PLAN.md           # Complete architectural design doc
├── PROMPT_1_REFACTOR_CORPUS.md   # Detailed refactoring instructions
├── PROMPT_2_BUILD_PROMPT_AGENT.md # Detailed build instructions
└── IMPLEMENTATION_SUMMARY.md      # This file
```

## Implementation Workflow

### Phase 1: Refactor corpus-agent (Use PROMPT_1)

**Goal:** Extract shared code to `/common` without breaking corpus-agent

**Key Actions:**
1. Create `/common/core/` with config.py, paths.py, registry.py
2. Create `/common/auth/youtube.py` with YouTube OAuth
3. Create `/common/cli/` with base CLI helpers
4. Update all corpus-agent imports to use `/common`
5. Test that corpus-agent still works

**Estimated Time:** 2-4 hours

**Success Criteria:**
- `/common` directory exists with complete structure
- `corpus --help` works
- `corpus status` works
- All tests pass
- No code duplication between `/common` and `corpus-agent/`

### Phase 2: Build prompt-agent (Use PROMPT_2)

**Goal:** Create new prompt-agent using `/common` infrastructure

**Key Actions:**
1. Create directory structure for prompt-agent
2. Implement core models (Prompt, PromptExecution)
3. Implement storage layer with SQLite
4. Implement placeholder substitution logic
5. Create Anthropic LLM provider plugin
6. Implement CLI commands (create, list, get, update, delete, apply)
7. Set up configuration system

**Estimated Time:** 4-6 hours

**Success Criteria:**
- `prompt --help` shows all commands
- Can create and list prompts
- Can apply prompts with all substitution types (@file, -, literal)
- Bash piping works between prompts
- Anthropic API integration works
- Data stored in shared fast-market directory

### Phase 3: Integration & Testing

**Goal:** Verify multi-agent cooperation

**Key Actions:**
1. Test cross-agent piping: `corpus get xyz | prompt apply summarize content=-`
2. Verify shared config directory works
3. Test that deleting one agent doesn't break the other
4. Write documentation

**Estimated Time:** 1-2 hours

## Quick Start Guide

### For the Refactoring (Phase 1)

```bash
# Read the detailed instructions
cat PROMPT_1_REFACTOR_CORPUS.md

# Key steps:
# 1. Create /common directory structure
# 2. Move files from corpus-agent/core/ to /common/core/
# 3. Extract YouTube OAuth to /common/auth/
# 4. Update imports throughout corpus-agent
# 5. Update pyproject.toml
# 6. Test that corpus-agent still works
```

### For Building prompt-agent (Phase 2)

```bash
# Read the detailed instructions
cat PROMPT_2_BUILD_PROMPT_AGENT.md

# Key steps:
# 1. Create prompt-agent directory
# 2. Implement core models and substitution logic
# 3. Implement storage layer
# 4. Create Anthropic provider plugin
# 5. Implement commands (create, list, apply, etc.)
# 6. Set up CLI entry point
# 7. Create configuration
```

## Architecture After Implementation

```
/mnt/project/
├── common/                        # Shared infrastructure
│   ├── core/
│   │   ├── config.py             # load_tool_config(tool_name)
│   │   ├── paths.py              # get_fastmarket_dir(), etc.
│   │   └── registry.py           # discover_plugins(), discover_commands()
│   ├── auth/
│   │   ├── base.py               # AuthProvider ABC
│   │   └── youtube.py            # YouTubeOAuth class
│   └── cli/
│       ├── base.py               # create_cli_group(tool_name)
│       └── helpers.py            # out(), _print_text()
│
├── corpus-agent/                  # Knowledge indexing agent
│   ├── cli/
│   ├── core/                     # corpus-specific (embedder, sync_engine, etc.)
│   ├── storage/
│   ├── plugins/
│   └── commands/
│
└── prompt-agent/                  # Prompt management agent
    ├── cli/
    ├── core/                     # prompt-specific (models, substitution)
    ├── storage/
    ├── plugins/                  # LLM providers (Anthropic, OpenAI, etc.)
    └── commands/

# Shared data directory (on user's system)
~/.local/share/fast-market/
├── config/
│   ├── corpus.yaml
│   ├── prompt.yaml
│   └── .env                      # Shared secrets
├── data/
│   ├── corpus/corpus.db
│   └── prompt/prompts.db
└── cache/
    ├── corpus/
    └── prompt/
```

## Key Design Decisions

### 1. Why `/common` Instead of a Separate Package?

**Decision:** Monorepo with shared `/common` directory

**Rationale:**
- **KISS:** Simpler than managing a separate PyPI package
- **Atomic changes:** Can update common code and agents together
- **Fast iteration:** No version pinning or release process
- **Shared evolution:** Common code evolves with agent needs

### 2. Why Tool-Specific Databases?

**Decision:** Each agent has its own database

**Rationale:**
- **Modularity:** Can delete prompt-agent without affecting corpus-agent
- **Schema independence:** Agents own their schemas, no conflicts
- **Granularity:** Clear boundaries between agent responsibilities

### 3. Why Shared Config Directory?

**Decision:** Single `~/.local/share/fast-market/` directory for all agents

**Rationale:**
- **DRY:** Don't duplicate YouTube OAuth, API keys, etc.
- **User experience:** One place to manage all configuration
- **Cross-agent cooperation:** Easy to reference shared resources

### 4. How to Handle Dynamic Placeholder Arguments?

**Decision:** Use `key=value` syntax parsed from `nargs=-1, type=UNPROCESSED`

**Example:**
```bash
prompt apply summarize content=@file.txt context="important meeting"
```

**Rationale:**
- Click doesn't support truly dynamic argument names
- This syntax is clear and explicit
- Allows multiple placeholders with distinct names
- Supports @file, -, and literal values

## Usage Examples After Implementation

### Example 1: Simple Prompt Application

```bash
# Create a summarization prompt
prompt create summarize \
  --content "Summarize the following text in 3 bullet points: {content}" \
  --description "Quick 3-point summary"

# Apply it to a file
prompt apply summarize content=@article.txt
```

### Example 2: Cross-Agent Pipeline

```bash
# Get content from corpus-agent, process with prompt-agent
corpus get yt-my-video-abc1 --what content | \
  prompt apply summarize content=-
```

### Example 3: Multi-Step Prompt Chain

```bash
# Extract facts, then summarize them
prompt create extract-facts \
  --content "Extract key facts from: {content}"

prompt create summarize \
  --content "Create a 3-sentence summary: {content}"

# Chain them together
prompt apply extract-facts content=@article.txt | \
  prompt apply summarize content=-
```

### Example 4: Multiple Placeholders

```bash
# Create translation prompt
prompt create translate \
  --content "Translate from {source_lang} to {target_lang}: {content}"

# Apply with multiple arguments
prompt apply translate \
  content=@article.txt \
  source_lang=en \
  target_lang=fr
```

## Testing Strategy

### Unit Tests

**Common:**
- `common/tests/test_config.py` - Config loading
- `common/tests/test_paths.py` - Path resolution
- `common/tests/test_registry.py` - Plugin discovery
- `common/tests/test_youtube_auth.py` - OAuth flow

**Prompt-agent:**
- `prompt-agent/tests/test_models.py` - Data models
- `prompt-agent/tests/test_store.py` - CRUD operations
- `prompt-agent/tests/test_substitution.py` - Placeholder resolution
- `prompt-agent/tests/test_commands/` - Each command

### Integration Tests

```python
# Test cross-agent cooperation
def test_corpus_to_prompt_pipeline():
    # Create test video in corpus
    # Extract content via corpus get
    # Pipe to prompt apply
    # Verify output
```

### Manual Verification

```bash
# Corpus-agent still works
corpus --help
corpus status
corpus sync youtube --limit 1

# Prompt-agent works
prompt --help
prompt create test --content "Test: {text}"
prompt apply test text="Hello"

# Cross-agent piping works
echo "Test content" | prompt apply test text=-
```

## Migration Checklist

### Pre-Flight (Before Starting)

- [ ] Backup current corpus-agent directory
- [ ] Read GOLDEN_RULES.md
- [ ] Read PROJECT.md
- [ ] Understand corpus-agent architecture
- [ ] Have test API keys ready (ANTHROPIC_API_KEY)

### Phase 1: Refactoring

- [ ] Create `/common` directory structure
- [ ] Move `core/{config,paths,registry}.py` to `/common/core/`
- [ ] Extract YouTube OAuth to `/common/auth/youtube.py`
- [ ] Create `/common/cli/{base,helpers}.py`
- [ ] Update all corpus-agent imports
- [ ] Update `corpus-agent/pyproject.toml`
- [ ] Run `corpus --help` - should work
- [ ] Run `corpus status` - should work
- [ ] Run all corpus-agent tests - should pass

### Phase 2: Building

- [ ] Create `prompt-agent/` directory
- [ ] Implement `core/models.py`
- [ ] Implement `core/substitution.py`
- [ ] Implement `storage/models.py`
- [ ] Implement `storage/store.py`
- [ ] Implement `plugins/base.py`
- [ ] Implement `plugins/anthropic/` plugin
- [ ] Implement all commands (create, list, get, update, delete, apply, setup)
- [ ] Create `cli/main.py`
- [ ] Create `pyproject.toml`
- [ ] Install and test: `pip install -e .`

### Phase 3: Integration

- [ ] Test `prompt create` works
- [ ] Test `prompt list` works
- [ ] Test `prompt apply` with @file works
- [ ] Test `prompt apply` with stdin works
- [ ] Test prompt chaining works
- [ ] Test cross-agent piping works
- [ ] Write README.md for prompt-agent
- [ ] Update root README.md

## Common Pitfalls to Avoid

### During Refactoring

❌ **DON'T:** Move files then fix imports later
✅ **DO:** Move one file at a time, fix imports immediately, test

❌ **DON'T:** Keep duplicated code "just in case"
✅ **DO:** Delete old code after confirming new imports work

❌ **DON'T:** Change behavior while refactoring
✅ **DO:** Pure refactoring only, no feature changes

### During Building

❌ **DON'T:** Hardcode paths or plugin names
✅ **DO:** Use discovery mechanisms and config

❌ **DON'T:** Swallow exceptions
✅ **DO:** FAIL LOUDLY with clear error messages

❌ **DON'T:** Add features beyond the spec
✅ **DO:** Start minimal, extend later

## Future Extensions

Once the foundation is solid, these extensions become easy:

### Prompt-agent v2
- Prompt versioning
- Template inheritance
- Execution history search
- Batch processing
- Streaming responses
- Cost tracking

### More Agents
- `publish-agent` - Cross-post to Twitter, Substack, Telegram
- `sales-agent` - Lead scoring, email sequences
- `trends-agent` - Signal detection from arXiv, HN, Twitter

All agents would:
- Share `/common` infrastructure
- Store data in `~/.local/share/fast-market/`
- Cooperate via bash pipes
- Follow the same plugin/command architecture

## Support & Troubleshooting

### Common Issues

**Problem:** Import errors after refactoring
**Solution:** Check that `/common` is in pyproject.toml packages list

**Problem:** corpus-agent can't find config
**Solution:** Verify config is at `~/.local/share/fast-market/config/corpus.yaml`

**Problem:** YouTube OAuth fails after refactoring
**Solution:** Check that `common.auth.youtube.YouTubeOAuth` is being used

**Problem:** prompt apply can't read file
**Solution:** Verify @file syntax and file exists

**Problem:** Piping doesn't work
**Solution:** Ensure prompt apply with `content=-` reads from stdin

### Where to Get Help

1. **GOLDEN_RULES.md** - Core principles
2. **corpus-agent/AGENTS.md** - Existing architecture patterns
3. **REFACTORING_PLAN.md** - Complete design rationale
4. **PROMPT_1/2 files** - Step-by-step instructions

## Success Metrics

You'll know you're done when:

✅ `corpus --help` works (corpus-agent not broken)
✅ `prompt --help` shows all commands
✅ `prompt create summarize --content "..."` creates a prompt
✅ `prompt apply summarize content=@file.txt` works
✅ `corpus get xyz | prompt apply summarize content=-` works
✅ Both agents share `~/.local/share/fast-market/` directory
✅ `/common` code is tool-agnostic (no hardcoded tool names)
✅ Deleting prompt-agent doesn't break corpus-agent
✅ All code follows GOLDEN_RULES (DRY, KISS, FAIL LOUDLY, etc.)

## Next Steps

1. **Read** REFACTORING_PLAN.md for full context
2. **Execute** PROMPT_1_REFACTOR_CORPUS.md
3. **Execute** PROMPT_2_BUILD_PROMPT_AGENT.md
4. **Celebrate** 🎉

---

*Remember: Slow is smooth, smooth is fast. Take it one file at a time, test constantly, and FAIL LOUDLY when something's wrong.*

# Fast-Market Multi-Agent Refactoring Plan

## Overview
Refactor `corpus-agent` to extract common infrastructure into `/common`, then build `prompt-agent` using the shared foundation.

---

## Phase 1: Extract Common Infrastructure

### 1.1 Create `/common` Directory Structure

```
common/
├── core/
│   ├── __init__.py
│   ├── config.py          # XDG-compliant config loading
│   ├── paths.py           # Shared path resolution
│   ├── registry.py        # Plugin/command discovery
│   └── models.py          # Base dataclasses (optional - agents may have their own)
├── auth/
│   ├── __init__.py
│   ├── youtube.py         # YouTube OAuth handling (from corpus-agent)
│   └── base.py            # Auth provider interface
├── cli/
│   ├── __init__.py
│   ├── base.py            # Base Click setup, context handling
│   └── helpers.py         # Common CLI utilities (out(), build_engine pattern)
└── storage/
    ├── __init__.py
    ├── base.py            # Base storage interface
    └── sqlite_base.py     # Shared SQLite utilities
```

### 1.2 What Goes Into `/common/core`

**From corpus-agent/core:**
- `config.py` → `/common/core/config.py` (MOVE)
  - Generalized config loading
  - Remove corpus-specific defaults
  - Add `load_tool_config(tool_name: str)` helper
  
- `paths.py` → `/common/core/paths.py` (MOVE)
  - Already tool-agnostic ✓
  - Keep as-is
  
- `registry.py` → `/common/core/registry.py` (MOVE)
  - Already generic plugin/command discovery ✓
  - Keep as-is

**Keep in corpus-agent/core:**
- `embedder.py` (corpus-specific)
- `embedding_server.py` (corpus-specific)
- `handle.py` (corpus-specific)
- `models.py` (corpus-specific: Document, Chunk, etc.)
- `sync_engine.py` (corpus-specific)
- `sync_errors.py` (corpus-specific)

### 1.3 What Goes Into `/common/auth`

**Extract from corpus-agent/plugins/youtube/plugin.py:**

```python
# common/auth/youtube.py
class YouTubeOAuth:
    """Shared YouTube OAuth client builder."""
    
    def __init__(self, client_secret_path: str):
        self.client_secret_path = client_secret_path
        self.token_path = Path(client_secret_path).parent / "token.json"
    
    def get_client(self):
        """Return authenticated YouTube API client."""
        # Extract OAuth logic from YouTubeTransport._get_client()
        ...
```

**Corpus-agent updates:**
- `plugins/youtube/plugin.py` imports from `common.auth.youtube`
- Remove duplicated OAuth code

### 1.4 What Goes Into `/common/cli`

**New files:**

```python
# common/cli/base.py
import click
from common.core.config import load_tool_config

def create_cli_group(tool_name: str) -> click.Group:
    """Standard Click group setup for all agents."""
    
    @click.group()
    @click.option("--verbose", "-v", is_flag=True, default=False)
    @click.pass_context
    def main(ctx: click.Context, verbose: bool) -> None:
        ctx.ensure_object(dict)
        ctx.obj["verbose"] = verbose
        ctx.obj["tool_name"] = tool_name
    
    return main


# common/cli/helpers.py
import json
import click

def out(data: object, fmt: str) -> None:
    """Standard output formatting."""
    if fmt == "json":
        click.echo(json.dumps(data, ensure_ascii=False, default=str))
    else:
        _print_text(data)

def _print_text(data: object) -> None:
    # ... (extract from corpus-agent/commands/helpers.py)
```

### 1.5 Migration Strategy

**Step-by-step:**

1. Create `/common` directory structure
2. Copy files to `/common` (don't move yet - keep duplicates)
3. Update imports in `/common` files to use relative imports
4. Update `corpus-agent` to import from `/common`
5. Run corpus-agent tests to verify nothing broke
6. Delete duplicated code from `corpus-agent`
7. Add `/common` to `corpus-agent/pyproject.toml` packages list

---

## Phase 2: Build `prompt-agent`

### 2.1 Directory Structure

```
prompt-agent/
├── cli/
│   ├── __init__.py
│   └── main.py           # Uses common.cli.base
├── core/
│   ├── __init__.py
│   └── models.py         # Prompt-specific models
├── storage/
│   ├── __init__.py
│   ├── models.py         # SQLAlchemy ORM
│   └── store.py          # Prompt CRUD operations
├── plugins/
│   ├── __init__.py
│   ├── base.py           # LLMProvider interface
│   ├── anthropic/
│   │   ├── __init__.py
│   │   ├── plugin.py
│   │   └── register.py
│   ├── openai/
│   │   ├── __init__.py
│   │   ├── plugin.py
│   │   └── register.py
│   └── flux/             # Future: image generation
│       ├── __init__.py
│       ├── plugin.py
│       └── register.py
├── commands/
│   ├── __init__.py
│   ├── base.py           # CommandManifest
│   ├── create/
│   │   └── register.py   # Create prompt
│   ├── list/
│   │   └── register.py   # List prompts
│   ├── get/
│   │   └── register.py   # Get prompt details
│   ├── update/
│   │   └── register.py   # Update prompt
│   ├── delete/
│   │   └── register.py   # Delete prompt
│   ├── apply/
│   │   └── register.py   # Apply prompt with substitutions
│   └── setup/
│       └── register.py   # Initial config setup
├── migrations/
│   ├── env.py
│   └── versions/
│       └── 0001_initial_schema.py
├── alembic.ini
├── pyproject.toml
└── README.md
```

### 2.2 Core Data Models

```python
# prompt-agent/core/models.py
from dataclasses import dataclass, field

@dataclass(slots=True)
class Prompt:
    """A reusable prompt template."""
    name: str                    # Unique identifier
    content: str                 # Template with {placeholders}
    description: str = ""
    model_provider: str = ""     # Default provider (empty = use global default)
    model_name: str = ""         # Specific model
    temperature: float = 0.7
    max_tokens: int = 2048
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class PromptExecution:
    """Record of a prompt execution."""
    prompt_name: str
    input_args: dict             # {placeholder: value}
    resolved_content: str        # After substitution
    output: str
    model_provider: str
    model_name: str
    timestamp: datetime
    metadata: dict = field(default_factory=dict)
```

### 2.3 Storage Schema

```sql
-- prompts table
CREATE TABLE prompts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    description TEXT,
    model_provider TEXT,
    model_name TEXT,
    temperature REAL DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 2048,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT,
    updated_at TEXT
);

-- executions table (optional - for history)
CREATE TABLE executions (
    id INTEGER PRIMARY KEY,
    prompt_name TEXT NOT NULL,
    input_args_json TEXT NOT NULL,
    resolved_content TEXT NOT NULL,
    output TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

### 2.4 LLM Provider Plugin Interface

```python
# prompt-agent/plugins/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class LLMRequest:
    prompt: str
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2048
    system: str | None = None

@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict | None = None
    metadata: dict | None = None


class LLMProvider(ABC):
    """Abstract base for LLM providers."""
    name: str
    
    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError
    
    @abstractmethod
    def list_models(self) -> list[str]:
        raise NotImplementedError


@dataclass
class PluginManifest:
    """What an LLM provider plugin contributes."""
    name: str
    provider_class: type
    cli_options: dict[str, list] = field(default_factory=dict)
```

### 2.5 CLI Commands Design

#### `prompt create`
```bash
prompt create summarize \
  --content "Summarize the following: {content}" \
  --description "Quick summarization" \
  --provider anthropic \
  --model claude-sonnet-4.5

# Or from file:
prompt create summarize --from-file template.txt
```

#### `prompt list`
```bash
prompt list
prompt list --format json
prompt list --provider anthropic
```

#### `prompt get`
```bash
prompt get summarize
prompt get summarize --format json
```

#### `prompt update`
```bash
prompt update summarize --content "New template: {content}"
prompt update summarize --temperature 0.9
```

#### `prompt delete`
```bash
prompt delete summarize
prompt delete summarize --force  # Skip confirmation
```

#### `prompt apply` (The main command)
```bash
# Direct substitution:
prompt apply summarize content="Long text here..."

# From file:
prompt apply summarize content=@article.txt

# From stdin:
cat article.txt | prompt apply summarize content=-

# Override model:
prompt apply summarize content=@file.txt --provider openai --model gpt-4

# Chain prompts (bash piping):
prompt apply extract-facts content=@article.txt | \
  prompt apply summarize content=-

# Multiple placeholders:
prompt apply translate \
  content=@article.txt \
  source_lang=en \
  target_lang=fr

# Save output:
prompt apply summarize content=@article.txt > summary.txt
```

### 2.6 Placeholder Substitution Logic

```python
# prompt-agent/core/substitution.py
import re
from pathlib import Path

def resolve_arguments(
    template: str,
    args: dict[str, str]
) -> str:
    """Resolve placeholders in template.
    
    Args:
        template: String with {placeholder} markers
        args: {placeholder: value}
               value can be:
               - literal string: "text"
               - file path: "@path/to/file.txt"
               - stdin: "-"
    
    Returns:
        Resolved template string
    """
    resolved = {}
    
    for key, value in args.items():
        if value == "-":
            # Read from stdin
            import sys
            resolved[key] = sys.stdin.read()
        elif value.startswith("@"):
            # Read from file
            path = Path(value[1:])
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            resolved[key] = path.read_text()
        else:
            # Literal value
            resolved[key] = value
    
    # Check for missing placeholders
    required = set(re.findall(r'\{(\w+)\}', template))
    missing = required - set(resolved.keys())
    if missing:
        raise ValueError(f"Missing arguments: {missing}")
    
    return template.format(**resolved)
```

### 2.7 Configuration

```yaml
# ~/.local/share/fast-market/config/prompt.yaml
default_provider: anthropic
default_model: claude-sonnet-4.5

providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    default_model: claude-sonnet-4.5
  
  openai:
    api_key_env: OPENAI_API_KEY
    default_model: gpt-4
  
  flux:
    api_key_env: FLUX_API_KEY
    default_model: flux-pro

# Optional: execution history
save_executions: true
max_execution_history: 1000
```

### 2.8 Anthropic Plugin Example

```python
# prompt-agent/plugins/anthropic/plugin.py
import os
from anthropic import Anthropic
from plugins.base import LLMProvider, LLMRequest, LLMResponse

class AnthropicProvider(LLMProvider):
    name = "anthropic"
    
    def __init__(self, config: dict):
        api_key = os.environ.get(config.get("api_key_env", "ANTHROPIC_API_KEY"))
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self.client = Anthropic(api_key=api_key)
        self.default_model = config.get("default_model", "claude-sonnet-4.5")
    
    def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.default_model
        
        response = self.client.messages.create(
            model=model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system=request.system or "",
            messages=[{"role": "user", "content": request.prompt}]
        )
        
        return LLMResponse(
            content=response.content[0].text,
            model=model,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            metadata={"id": response.id},
        )
    
    def list_models(self) -> list[str]:
        return [
            "claude-opus-4.5",
            "claude-sonnet-4.5",
            "claude-haiku-4.5",
        ]
```

### 2.9 Apply Command Implementation

```python
# prompt-agent/commands/apply/register.py
import click
from commands.base import CommandManifest
from commands.helpers import build_engine, out

def register(plugin_manifests: dict) -> CommandManifest:
    # Build provider choices from plugins
    provider_choices = list(plugin_manifests.keys())
    
    @click.command("apply")
    @click.argument("prompt_name")
    @click.option("--provider", type=click.Choice(provider_choices), default=None)
    @click.option("--model", default=None)
    @click.option("--temperature", type=float, default=None)
    @click.option("--max-tokens", type=int, default=None)
    @click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
    @click.pass_context
    def apply_cmd(ctx, prompt_name, provider, model, temperature, max_tokens, fmt, **kwargs):
        from core.substitution import resolve_arguments
        from storage.store import PromptStore
        
        store = PromptStore()
        prompt = store.get_prompt(prompt_name)
        if not prompt:
            click.echo(f"Prompt not found: {prompt_name}", err=True)
            return 1
        
        # Extract placeholder arguments (everything not in known options)
        placeholder_args = {k: v for k, v in kwargs.items() 
                          if k not in ["provider", "model", "temperature", "max_tokens", "format"]}
        
        # Resolve placeholders
        resolved = resolve_arguments(prompt.content, placeholder_args)
        
        # Determine provider
        provider_name = provider or prompt.model_provider or _get_default_provider()
        providers = build_engine(ctx.obj["verbose"])
        llm_provider = providers[provider_name]
        
        # Build request
        from plugins.base import LLMRequest
        request = LLMRequest(
            prompt=resolved,
            model=model or prompt.model_name,
            temperature=temperature or prompt.temperature,
            max_tokens=max_tokens or prompt.max_tokens,
        )
        
        # Execute
        response = llm_provider.complete(request)
        
        # Output
        if fmt == "json":
            out({
                "prompt_name": prompt_name,
                "output": response.content,
                "model": response.model,
                "usage": response.usage,
            }, fmt)
        else:
            click.echo(response.content)
    
    # Add dynamic placeholder arguments
    # (This is tricky - Click needs to know argument names upfront)
    # Solution: Accept all unknown options via **kwargs
    apply_cmd = click.argument(
        "placeholder_args",
        nargs=-1,
        type=click.UNPROCESSED,
    )(apply_cmd)
    
    return CommandManifest(
        name="apply",
        click_command=apply_cmd,
    )
```

---

## Phase 3: Shared Data & Config Space

### 3.1 Directory Layout

All agents share the same XDG base directories:

```
~/.local/share/fast-market/
├── config/
│   ├── corpus.yaml
│   ├── prompt.yaml
│   └── .env              # Shared secrets
├── data/
│   ├── corpus/
│   │   └── corpus.db
│   └── prompt/
│       └── prompts.db
└── cache/
    ├── corpus/
    └── prompt/
```

### 3.2 Config Loading Pattern

```python
# common/core/config.py
from common.core.paths import get_tool_config

def load_tool_config(tool_name: str) -> dict:
    """Load tool-specific config from shared fast-market directory."""
    path = get_tool_config(tool_name)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}

# In each agent:
from common.core.config import load_tool_config
config = load_tool_config("corpus")  # or "prompt"
```

### 3.3 Cross-Agent Cooperation Example

```bash
# Corpus-agent provides content
corpus get yt-my-video-abc1 --what content > video_transcript.txt

# Prompt-agent processes it
prompt apply summarize content=@video_transcript.txt

# Or direct pipe:
corpus get yt-my-video-abc1 --what content | \
  prompt apply summarize content=-
```

---

## Phase 4: Implementation Checklist

### Refactoring Corpus-Agent

- [ ] Create `/common` directory structure
- [ ] Copy `core/{config,paths,registry}.py` to `/common/core/`
- [ ] Extract YouTube OAuth to `/common/auth/youtube.py`
- [ ] Create `/common/cli/{base,helpers}.py`
- [ ] Update `corpus-agent` imports to use `/common`
- [ ] Test corpus-agent still works
- [ ] Update `corpus-agent/pyproject.toml` to include `/common` packages
- [ ] Delete duplicated code from `corpus-agent`

### Building Prompt-Agent

- [ ] Create `prompt-agent` directory structure
- [ ] Implement `core/models.py` (Prompt, PromptExecution)
- [ ] Implement `storage/{models,store}.py`
- [ ] Create Alembic migrations
- [ ] Implement `plugins/base.py` (LLMProvider interface)
- [ ] Implement `plugins/anthropic/` plugin
- [ ] Implement `plugins/openai/` plugin (optional)
- [ ] Implement `core/substitution.py`
- [ ] Implement commands: create, list, get, update, delete, apply
- [ ] Write `cli/main.py` using `common.cli.base`
- [ ] Create `pyproject.toml` with `/common` dependency
- [ ] Write tests
- [ ] Write README.md

### Documentation

- [ ] Update `GOLDEN_RULES.md` to mention `/common`
- [ ] Create `/common/README.md`
- [ ] Create `prompt-agent/README.md`
- [ ] Update root `README.md` to explain multi-agent architecture

---

## Design Decisions & Rationale

### Why `/common` Instead of a Separate Package?

- **KISS**: Simpler than managing separate PyPI package
- **Monorepo benefits**: Atomic changes across agents
- **Shared evolution**: Common code evolves with agents

### Why Tool-Specific Databases?

- **Modularity**: Delete `prompt-agent` → corpus still works
- **Schema independence**: Each agent owns its schema
- **Granularity**: Clear boundaries

### Why Shared Config Directory?

- **DRY**: Don't duplicate YouTube OAuth setup
- **User experience**: One place for all secrets
- **Cross-agent cooperation**: Easy to reference

### Dynamic Placeholder Arguments?

Click doesn't support truly dynamic arguments. Solutions:

1. **Accepted:** Use `nargs=-1, type=UNPROCESSED` and parse manually
2. **Alternative:** Require `--arg name=value` syntax
3. **Future:** Build custom Click extension

Recommendation: Start with option 2 for clarity:
```bash
prompt apply summarize --arg content=@file.txt --arg context="Important"
```

---

## Testing Strategy

### Common Tests
```
common/
└── tests/
    ├── test_config.py
    ├── test_paths.py
    ├── test_registry.py
    └── test_youtube_auth.py
```

### Prompt-Agent Tests
```
prompt-agent/
└── tests/
    ├── test_models.py
    ├── test_store.py
    ├── test_substitution.py
    ├── test_anthropic_plugin.py
    └── test_commands/
        ├── test_create.py
        ├── test_apply.py
        └── ...
```

### Integration Tests
```
tests/
└── integration/
    └── test_corpus_prompt_pipeline.py
```

---

## Migration Path

1. **Week 1:** Refactor corpus-agent (extract to `/common`)
2. **Week 2:** Build prompt-agent MVP (create, list, get, apply with Anthropic)
3. **Week 3:** Add remaining commands (update, delete) and OpenAI plugin
4. **Week 4:** Integration testing, documentation, polish

---

## Future Extensions

### Prompt-Agent v2
- Template inheritance (base prompts + overrides)
- Prompt versioning
- Execution history search
- Batch apply (multiple inputs)
- Streaming responses
- Cost tracking per execution

### More Agents
- `publish-agent`: Cross-posting to Twitter, Substack, Telegram
- `sales-agent`: Lead scoring, email sequences
- `trends-agent`: Signal detection, content ideation

All sharing `/common` infrastructure and cooperating via pipes!
