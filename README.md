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

## CLI reference

### Global flag

```bash
corpus --verbose COMMAND   # or: corpus -v COMMAND
```

`--verbose` / `-v` prints all internal logs (embedding model loading, sync progress, errors) to **stderr**. Without it, **only result output goes to stdout** — this keeps the CLI pipeable with `jq`, `xargs`, etc.

```bash
# Silent — stdout is clean JSON
corpus search "landing page" --format json | jq '.[0].handle'

# Verbose — logs on stderr, JSON on stdout, both usable
corpus -v search "landing page" --format json | jq '.[0].handle'
```

---

### sync

```bash
corpus sync [OPTIONS]
```

Fetch and index new content.

| Option | Default | Description |
|--------|---------|-------------|
| `--source obsidian\|youtube\|all` | `all` | Which source to sync |
| `--mode new\|backfill` | `new` | `new`: only items newer than last sync. `backfill`: ignore last-sync timestamp |
| `--limit N` | 10 obsidian / 5 youtube | Max items to fetch |
| `--clean` | off | Wipe entire index before syncing |
| `--format json\|text` | `text` | Output format |

```bash
corpus sync                                      # sync all sources, new items only
corpus sync --source youtube --limit 20          # last 20 YouTube videos
corpus sync --source obsidian --mode backfill    # reprocess all Obsidian notes
corpus sync --clean                              # wipe index and start fresh
corpus sync --format json                        # machine-readable result
```

---

### search

```bash
corpus search QUERY [OPTIONS]
```

Search the index. Returns handles, titles, excerpts, and scores.

| Option | Default | Description |
|--------|---------|-------------|
| `--mode semantic\|keyword` | `semantic` | Semantic uses embeddings; keyword uses SQLite FTS |
| `--limit N` | `5` | Max results |
| `--source obsidian\|youtube` | — | Filter by source |
| `--type short\|long` | — | YouTube only: short ≤ 60s, long > 60s |
| `--min-duration N` | — | Min duration in seconds |
| `--max-duration N` | — | Max duration in seconds |
| `--since YYYY-MM-DD` | — | Updated after date |
| `--until YYYY-MM-DD` | — | Updated before date |
| `--min-size N` | — | Min content length in chars (useful for Obsidian) |
| `--max-size N` | — | Max content length in chars |
| `--format json\|text` | `text` | Output format |

```bash
corpus search "landing page"
corpus search "IA" --source youtube --type long
corpus search "startup" --since 2024-01-01 --limit 10
corpus search "notes" --source obsidian --min-size 1000
corpus search "topic" --format json | jq '.[0].handle'
```

**Chaining example — get full transcript of top result:**
```bash
corpus search "bureaucratie" --source youtube --format json \
  | jq -r '.[0].handle' \
  | xargs corpus get --what content
```

---

### get

```bash
corpus get HANDLE [OPTIONS]
```

Retrieve a document by its **handle** (e.g. `yt-my-video-a3f2`) or by `source_id` (e.g. `Note.md`).

| Option | Default | Description |
|--------|---------|-------------|
| `--what meta\|content\|all` | `meta` | `meta`: all fields except raw text. `content`: raw text only. `all`: everything |
| `--format json\|text` | `text` | Output format |

```bash
corpus get yt-my-video-a3f2                        # metadata only
corpus get yt-my-video-a3f2 --what content         # transcript/text only
corpus get yt-my-video-a3f2 --what all --format json
corpus get "Note.md" --what meta
```

**Handles** are stable slugs assigned at index time: `yt-{title-slug}-{4char-hash}` for YouTube, `ob-{title-slug}-{4char-hash}` for Obsidian. They are shell-safe (no spaces, no special characters) and survive reindexing.

---

### delete

```bash
corpus delete HANDLE [OPTIONS]
```

Remove a document and all its chunks from the index.

```bash
corpus delete yt-my-video-a3f2
corpus delete "Note.md"
corpus delete yt-my-video-a3f2 --format json
```

---

### reindex

```bash
corpus reindex [--source obsidian|youtube|all] [--format json|text]
```

Rebuild embeddings for all indexed documents without re-fetching from source. Use after changing the embedding model or chunking logic.

---

### status

```bash
corpus status [--format json|text]
```

Print document counts per source.

---

### serve

```bash
corpus serve [--port PORT]   # default: 8000
```

Start the HTTP API and web frontend.

---

## Web frontend

Start the server and open `http://localhost:8000` (redirects to `/ui`).

| URL | Description |
|-----|-------------|
| `/ui` | Homepage with links to all sections |
| `/ui/items` | Browse all indexed documents, filter by source, expand content, delete |
| `/ui/search` | Semantic or keyword search with content expansion and delete |
| `/ui/status` | Document counts and total video duration |
| `/docs` | OpenAPI interactive docs |

---

## HTTP API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sources` | List source plugins |
| GET | `/items` | List documents (supports `source`, `limit`, `video_type`, `min_duration`, `max_duration`, `since`, `until`, `min_size`, `max_size`) |
| GET | `/document/{plugin}/{id}` | Get full document including raw text |
| GET | `/handle/{handle}` | Get document by handle |
| DELETE | `/document/{plugin}/{id}` | Delete document from index |
| POST | `/sync` | `{"source": "obsidian", "mode": "new", "limit": 10}` |
| POST | `/reindex` | `{"source": "youtube"}` |
| GET | `/search` | `?q=…&mode=semantic&limit=5` (same filters as CLI) |

---

## Adding a new source plugin

1. Create `plugins/yourplugin/` with `__init__.py` and `plugin.py`
2. Implement the `SourcePlugin` ABC from `plugins/base.py`:
   - `name: str` — plugin identifier
   - `list_items(limit, since) -> list[ItemMeta]`
   - `fetch(item_meta) -> Document`
3. Register it in `core/registry.py` → `build_plugins()`
4. Add it to the `--source` choices in `cli/main.py`

---

## Running tests

```bash
cd corpus-agent
pip install -e ".[dev]"
pytest
```

Tests use an in-memory SQLite store and a `DummyEmbedder` — no ML model download needed.
The Obsidian plugin test creates a temporary vault via `tmp_path` (pytest built-in).
No external fixtures or data files are required.
