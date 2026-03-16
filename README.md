# fast-market / corpus-agent

Tool to accelerate marketing for web creators by indexing your content corpus (Obsidian notes, YouTube videos) and making it searchable.

---

## corpus-agent

A local indexing and search agent that ingests content from pluggable sources, chunks and embeds it, and exposes keyword + semantic search via CLI or HTTP API.

### Requirements

- Python 3.11+
- (Optional, for semantic search) `sentence-transformers` — requires PyTorch

### Installation

```bash
cd corpus-agent
pip install -e .

# For semantic search (large download):
pip install -e ".[ml]"

# For YouTube support:
pip install -e ".[youtube]"

# For audio fallback via Whisper (when no transcript available):
pip install -e ".[whisper]"
```

### First-time setup

Run the interactive wizard to generate `config.yaml`:

```bash
corpus setup
```

This writes `config.yaml` and a stub `.env` at the project root. Neither is committed to git.

**Manual config** — you can also write `config.yaml` directly:

```yaml
db_path: data/corpus.db
embed_batch_size: 32
obsidian:
  vault_path: /absolute/path/to/vault
youtube:
  channel_id: UCxxxxxxxxxxxxxxxxxxxxxxxx
  client_secret_path: /path/to/client_secret.json
whisper:
  model: base   # tiny | base | small — only used if no transcript available
```

---

### Finding your YouTube channel ID

Go to [commentpicker.com/youtube-channel-id.php](https://commentpicker.com/youtube-channel-id.php), enter your channel URL, and copy the ID (starts with `UC...`).

---

### Getting a YouTube `client_secret.json`

You need this to let the agent list videos from your channel via the YouTube Data API.

**1. Create a Google Cloud project**
Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project (or reuse one).

**2. Enable the YouTube Data API v3**
- Go to **APIs & Services → Library**
- Search for "YouTube Data API v3" and click **Enable**

**3. Configure the OAuth consent screen**
- Go to **APIs & Services → OAuth consent screen**
- User type: **External**
- Fill in app name and your email — everything else can be left blank
- Under **Scopes**, add `youtube.readonly`
- Under **Test users**, add your own Google account email
- Save

**4. Create OAuth credentials**
- Go to **APIs & Services → Credentials**
- Click **+ Create Credentials → OAuth client ID**
- Application type: **Desktop app**, name it anything
- Click **Create**, then **Download JSON**
- Save the file somewhere safe (e.g. `~/.config/corpus-agent/client_secret.json`)

**5. First run — browser auth**
The first time you run `corpus sync --source youtube`, a browser window will open asking you to authorize the app with your Google account. After approval, a `token.json` is saved next to your `client_secret.json` for future runs — no browser needed after that.

> **Note:** The app will show a warning ("unverified app") since it's your own private OAuth app. Click "Advanced → Go to app" to proceed.

---

### CLI usage

All commands are under the `corpus` entry point.

#### Sync new content

```bash
# Sync new items from all sources (default: last 10 items)
corpus sync

# Sync only Obsidian, backfill mode (re-process everything), up to 50 items
corpus sync --source obsidian --mode backfill --limit 50

# Sync only YouTube, new items only
corpus sync --source youtube --mode new --limit 5
```

`--mode new` only fetches items newer than the last sync.
`--mode backfill` ignores the last-sync timestamp and re-processes from scratch.

#### Search

```bash
# Semantic search (requires sentence-transformers)
corpus search "how to structure a landing page"

# Keyword (FTS) search — no ML deps required
corpus search "landing page" --mode keyword

# Return more results
corpus search "landing page" --limit 10
```

#### Reindex (rebuild embeddings without re-fetching)

```bash
corpus reindex
corpus reindex --source obsidian
```

Use this after changing the embedding model or chunking logic.

#### Status

```bash
corpus status
```

Prints document counts per source plugin.

---

### HTTP API

Start the server:

```bash
corpus serve           # default port 8000
corpus serve --port 9000
```

Endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sources` | List available source plugins |
| GET | `/items?source=obsidian&limit=20` | List indexed documents |
| POST | `/sync` | `{"source": "obsidian", "mode": "new", "limit": 10}` |
| POST | `/reindex` | `{"source": "youtube"}` |
| GET | `/search?q=hello&mode=semantic&limit=5` | Search (`keyword` or `semantic`) |

Interactive docs at `http://localhost:8000/docs`.

---

### Adding a new source plugin

1. Create `plugins/yourplugin/` with `__init__.py` and `plugin.py`
2. Implement the `SourcePlugin` ABC from `plugins/base.py` — requires `name`, `list_items()`, and `fetch()`
3. Register it in `core/registry.py` → `build_plugins()`
4. Add it to the `--source` choices in `cli/main.py`

---

### Running tests

```bash
cd corpus-agent
pip install -e ".[dev]"
pytest
```

Tests use an in-memory SQLite store and a `DummyEmbedder` — no ML model download needed.
The Obsidian plugin test creates a temporary vault via `tmp_path` (pytest built-in).
No external fixtures or data files are required.
