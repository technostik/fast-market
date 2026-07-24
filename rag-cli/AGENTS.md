# rag-agent

## Purpose
Vectorless, reasoning-based RAG CLI tool. Builds hierarchical document trees (table-of-contents style) with LLM-generated summaries per node, and retrieves answers through agentic reasoning — the LLM navigates the tree via tool calls, not cosine similarity.

Inspired by [PageIndex](https://github.com/VectifyAI/PageIndex).

## Architecture

```
rag-cli/
├── rag_entry/          # CLI entry point
├── cli/                # Click group + command discovery
├── core/
│   ├── extractors.py   # PDF (pypdf) + Markdown text extraction + file discovery
│   ├── tree_builder.py # Tree construction (ported from PageIndex)
│   ├── tree_search.py  # Agentic retrieval: list_children, read_node tools
│   └── collection_pointer.py # Active collection pointer
├── storage/
│   ├── models.py       # Collection, Document, TreeNode, CollectionMember, IndexRun
│   ├── store.py        # SQLAlchemy CRUD
│   └── migrations/     # Alembic migrations
├── plugins/corpus/     # Bridge to corpus-cli's SQLite
├── commands/
│   ├── collection/     # create, use, list, show, delete
│   ├── index/          # rag index <path>
│   ├── ask/            # rag ask "<question>"
│   ├── direct_ask/     # rag direct-ask <path> "<question>"
│   ├── list/           # rag list
│   ├── show/           # rag show <handle> --tree
│   ├── delete/         # rag delete <handle>
│   └── setup/          # rag setup run/wizard/edit
└── tests/
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `rag collection create <name>` | Create a named collection |
| `rag collection use <name>` | Set active collection pointer |
| `rag collection list` | List all collections |
| `rag collection show <name>` | Show collection members and scopes |
| `rag collection delete <name>` | Delete collection (not documents) |
| `rag index <path>` | Index a local PDF/Markdown file or directory recursively |
| `rag index cleanup --all --force` | Drop and recreate all index data |
| `rag index <path> --tag <name>` | Add sub-scope tag to indexed doc |
| `rag index <path> --mode reindex` | Regenerate summaries only |
| `rag ask "<question>"` | Ask about collection documents |
| `rag direct-ask <path> "<question>"` | One-shot ask on file or directory |
| `rag direct-ask <path> "<question>"` --keep | Keep document after asking |
| `rag direct-ask <path> "<question>"` --verbose | Show agent tool call reflections |
| `rag list` | List indexed documents |
| `rag show <handle> --tree` | ASCII tree render |
| `rag delete <handle> --collection <name>` | Remove from collection |
| `rag delete <handle> --purge` | Delete document everywhere |
| `rag setup run` | Run setup wizard |

## Data Model

- **Collection** — named, isolated set of documents
- **Document** — a unique physical file/content with content_hash for idempotence
- **TreeNode** — hierarchical node in the document tree
- **CollectionMember** — ties Document to Collection with optional root_node_id scoping
- **IndexRun** — tracks indexing runs (success/failed/running)

## Key Design Decisions

### No vector DB
Retrieval is done through agentic reasoning: the LLM navigates the tree via `list_children` and `read_node` tool calls, not cosine similarity.

### Collection isolation
Every read during `rag ask` goes through a JOIN via CollectionMember filtered on collection_id. A membership with root_node_id scopes access to descendants only.

### Active collection pointer
Replicates the `active_profile` pattern. Resolution order:
1. `--collection` option
2. Active pointer (`rag collection use <name>`)
3. Error telling user to create/use a collection

### PageIndex vendored as read-only
The `_vendor/pageindex-upstream/` directory is read-only reference material. It is never imported at runtime — tree-building logic is ported into `core/tree_builder.py` using `common.llm` instead of litellm.

## Dependencies

- `click`, `pyyaml`, `structlog`, `sqlalchemy`, `alembic`, `pypdf`
- Uses `common.llm` for LLM calls (never litellm directly)

## Related Documentation

- `GOLDEN_RULES.md` — DRY, KISS, CODE IS LAW, FAIL LOUDLY
- `common/llm/AGENTS.md` — LLM provider abstraction
- `common/agent/AGENTS.md` — agentic loop (not used directly; tree_search.py has its own lightweight loop)
