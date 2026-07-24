# rag-cli

Vectorless, reasoning-based RAG tool for fast-market.

No vector database. No similarity chunking. A hierarchical tree (table-of-contents style) is built per document, with LLM-generated summaries per node, and retrieval is done through **agentic reasoning** — the LLM navigates the tree via tool calls.

## Install

```bash
cd rag-cli
pip install -e .
```

## Quick Start

```bash
# Create a collection
rag collection create research
rag collection use research

# Index a document
rag index ./paper.pdf --collection research
rag index ./notes.md --collection research

# Index a directory recursively
rag index ./docs/ --collection research

# Ask a question
rag ask "What are the main findings?"

# One-shot ask (no collection needed)
rag direct-ask ./paper.pdf "Summarize section 3"
rag direct-ask ./notes.md "What is the roadmap?" --keep

# Ask about all documents in a directory
rag direct-ask ./docs/ "What are the main topics covered?" --verbose
```

## Commands

### Collections

```bash
rag collection create <name> [--description TEXT]
rag collection use <name>
rag collection list [--format json|text]
rag collection show <name>
rag collection delete <name>
```

### Indexing

```bash
rag index <path> [--collection NAME] [--tag NAME] [--mode new|reindex]
rag index cleanup --all --force
```

- `<path>`: A single file (`.pdf`, `.md`, `.markdown`) or a directory (recursive)
- `--mode new` (default): full extraction + tree building + summaries
- `--mode reindex`: regenerate summaries only (no re-extraction)
- `--tag`: assign a sub-scope tag based on heading matching
- `cleanup --all --force`: drop and recreate all index data (no confirmation prompt)

### Querying

```bash
rag ask "<question>" [--collection NAME] [--model NAME] [--format json|text]
rag direct-ask <path> "<question>" [--model NAME] [--format json|text] [--keep] [--verbose]
```

- `<path>`: A single file or directory (recursive)
- `--keep`: Preserve indexed documents after answering
- `--verbose`: Show agent tool call reflections during search

### Management

```bash
rag list [--collection NAME] [--format json|text]
rag show <handle> --tree
rag delete <handle> --collection <name>
rag delete <handle> --purge
```

### Setup

```bash
rag setup run    # Run toolsetup wizard
rag setup edit   # Open config in editor
```

## Shell Completion

Enable tab completion for bash, zsh, or fish:

```bash
# Install completion (adds to your shell config)
rag --install-completion

# Or show the completion script to add manually
rag --show-completion
```

### What Autocompletes

| Command | Autocomplete |
|---------|--------------|
| `rag index <path>` | File/directory paths |
| `rag direct-ask <path>` | File/directory paths |
| `rag collection use/show/delete <name>` | Collection names from database |
| `rag ask/list --collection <name>` | Collection names from database |
| `rag show/delete <handle>` | Document handles from database |
| `rag index --mode` | `new`, `reindex` |
| `rag index --source` | `local_file`, `corpus` |
| `*/--format` | `json`, `text` |

## How It Works

1. **Extract**: PDF pages via `pypdf`, Markdown via heading hierarchy
2. **Build**: Hierarchical tree with node IDs (ported from PageIndex algorithm)
3. **Enrich**: LLM-generated summaries per node
4. **Persist**: Atomic SQLAlchemy transaction (incomplete tree = rollback)
5. **Retrieve**: LLM agent navigates tree via `list_children`/`read_node` tool calls

## Configuration

Uses the standard fast-market LLM config:

```yaml
# ~/.config/fast-market/profiles/<profile>/common/llm/config.yaml
default_provider: anthropic
providers:
  anthropic:
    type: anthropic
    model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
```

## Architecture

See [AGENTS.md](AGENTS.md) for architecture details.
