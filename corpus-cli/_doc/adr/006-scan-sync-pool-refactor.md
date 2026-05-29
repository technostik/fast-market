# ADR 006 — Split sync into scan + sync with persistent pool

## Status
Accepted — implemented 2026-05-29

---

## Context

The old `corpus sync` command fused two concerns in a single run:

1. **Discovery** (`plugin.list_items`) — find what needs indexing  
2. **Fetching** (`plugin.fetch`) — retrieve the raw content and index it

This caused two independent pain points:

**YouTube quota burn.** `corpus sync --non-public` called `list_items` via the YouTube Data API on every run, consuming quota even when there were no new videos. A full channel inventory can cost hundreds of quota units per invocation.

**Obsidian unwanted content.** `corpus sync --source obsidian` walked the entire vault and indexed everything it found. There was no way to select a subset of folders or files without configuring `exclude_dirs`. The user had no interactive control over what entered the corpus.

---

## Decision

### 1. Persistent pool table

A new `pool_items` table acts as a staging area between discovery and fetching.

```
pool_items
  source_plugin  TEXT   (youtube | obsidian)
  source_id      TEXT   (video_id | vault-relative path)
  status         TEXT   (pending | synced | excluded | failed)
  metadata_json  TEXT   (JSON: title, privacy_status, duration_seconds, …)
  added_at       TEXT
  synced_at      TEXT
  UNIQUE(source_plugin, source_id)
```

**Migration note:** existing YouTube documents are inserted into `pool_items` with `status='synced'` so the first `scan` run skips them correctly. Obsidian starts with an empty pool (the user must explicitly select content via the TUI).

### 2. `corpus scan` — discovery only

`scan` calls `plugin.list_items()` and adds new items to the pool. It never calls `plugin.fetch()`.

**YouTube scan** (`corpus scan --source youtube`):
- Calls the YouTube Data API with `scan_all=True`, fetching the **full channel inventory** (all privacy statuses: public, private, unlisted, membersOnly).
- Passes already-synced and excluded IDs as "known" so the API skips them (quota efficiency).
- Pending and failed IDs are *not* passed as known — the API returns them with fresh metadata so privacy status changes are detected.
- Adds genuinely new videos to the pool as `pending`.
- For existing `pending`/`failed` items whose `privacy_status` changed: updates pool metadata and, if the video became `public`, resets status to `pending` so the next public sync can pick it up.

**Obsidian scan** (`corpus scan --source obsidian`):
- Opens a **Textual TUI** showing the vault directory tree.
- Each file and folder shows its current status (new / pending / synced / excluded).
- Keyboard actions: `[i]` include, `[r]` remove from pool, `[x]` exclude, `[f]` toggle Full/New-only view.
- Changes are written to the pool immediately (no confirmation step).
- Excluded items persist in the pool table (`status='excluded'`) so they stay hidden on future scans.

### 3. `corpus sync` — fetch from pool only

`corpus sync` reads `pending` items from `pool_items` and calls `plugin.fetch()` → chunk → embed → index on each one.

**YouTube: public vs non-public routing**

Pool items carry `privacy_status` in their metadata. `sync` filters accordingly:

| Command | Pool items processed | Transcript method |
|---|---|---|
| `corpus sync` (default) | `privacy_status == "public"` | RSS / youtube-transcript-api (no Data API quota) |
| `corpus sync --non-public` | `privacy_status != "public"` | YouTube Data API captions (needs OAuth) |

Default limit: **YouTube = 10**, **Obsidian = 0 (all)**.

`--mode backfill` and `--mode reindex` bypass the pool entirely (direct store operations, same behaviour as before).

---

## Handling privacy status changes over time

YouTube videos can change visibility (private → public, unlisted → public, etc.) after they are first scanned. The pool design handles this naturally:

1. **Run `corpus scan`** — the scan always fetches fresh video metadata from the API for all non-synced items. When a video's privacy status changes the pool item's `metadata_json` is updated immediately.
2. **Automatic re-queue** — if a `failed` item becomes `public` (meaning a previous API-caption attempt failed but the video is now fetchable without the API), `scan` resets its pool status to `pending`. It will be picked up by the next `corpus sync`.
3. **Pending items** — a `pending` item whose privacy changes from private → public will simply be processed on the next `corpus sync` (no `--non-public` needed), because the filter reads the latest metadata.

**Summary:** the user does not need to do anything special when a video's visibility changes. Running `corpus scan` before `corpus sync` is sufficient.

**What does NOT trigger a re-queue:**
- A synced video becoming non-public — it is already indexed; its privacy status in the pool is updated but no re-sync is performed.
- An excluded video changing visibility — excluded means the user explicitly does not want it; privacy changes do not override that.

---

## Typical workflow

```bash
# 1. Discover all new videos and refresh privacy statuses
corpus scan --source youtube

# 2. Index public videos (fast, no API quota for transcripts)
corpus sync --source youtube

# 3. Index non-public videos when needed (uses API captions)
corpus sync --source youtube --non-public

# 4. Select Obsidian notes interactively
corpus scan --source obsidian
# → TUI opens: navigate, [i]nclude folders/files, [q]uit

# 5. Index all selected Obsidian notes
corpus sync --source obsidian
```

---

## Trade-offs accepted

| Concern | Trade-off |
|---|---|
| YouTube scan always costs API quota | Unavoidable — RSS only exposes public videos; full inventory requires the Data API. Batched in pages of 100, max 1 000 videos per scan run. |
| Two-step workflow (scan then sync) | More explicit control; scan is cheap when nothing is new. |
| Privacy status in pool may lag reality | Acceptable — `scan` is the refresh gate. Users who need up-to-date status run `scan` first. |
| Obsidian fresh start | Intentional — gives the user full control over what enters the corpus from the vault. |

---

## Files changed

| File | Change |
|---|---|
| `storage/models.py` | New `PoolItemModel` |
| `storage/sqlalchemy_store.py` | Pool CRUD: `upsert_pool_item`, `add_to_pool`, `remove_from_pool`, `get_pool_items`, `get_pool_ids`, `mark_pool_item`, `pool_stats` |
| `migrations/versions/0004_add_pool_items_table.py` | Creates `pool_items`, pre-populates YouTube synced items |
| `plugins/youtube/plugin.py` | New `scan_all` param on `list_items` / `_list_items_via_api` |
| `commands/scan/register.py` | New command: YouTube full-inventory scan + Obsidian TUI launcher |
| `commands/scan/obsidian_tui.py` | Textual TUI for interactive vault selection |
| `commands/sync/register.py` | Rewritten: reads from pool; adds `--non-public` privacy routing |
| `core/sync_engine.py` | New `sync_pool_items()` method |
| `pyproject.toml` | Added `textual>=0.52` dependency |
