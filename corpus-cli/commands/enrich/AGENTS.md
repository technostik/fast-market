# commands/enrich/

Implements the `corpus enrich` CLI command.

## Purpose

Bulk-fill metadata for non-synced (pool) YouTube items directly from yt-dlp —
no YouTube Data API quota involved. Enrichment writes metadata back to the pool
so it shows up in `corpus list` and the webux Corpus Browser without re-scanning.

Shared core logic lives in `core/pool_enrich.py` and is also used by the
corpus_browser webux plugin (POST /api/corpus_browser/enrich) — keep both
surfaces in sync.

## Options

- `--source` — plugin to enrich; defaults to the youtube plugin when present.
- `--state` — `not-synced` (default) covers pending/failed/excluded; or one state.
- `--handles` — restrict to specific pool handles (e.g. `pool:youtube:<id>`).
- `--limit` / `-l`, `--concurrency` / `-c`, `--cookies`.

## Bot challenge handling

When yt-dlp reports "Sign in to confirm you're not a bot", the run pauses
immediately: pending fetches are cancelled, the cooldown is persisted
(`enrich_bot_pause.json` in the corpus data dir), and the command exits with
code 2 and a clear message. Runs within the cooldown window (config
`youtube.enrich_bot_cooldown`, default 3600s) refuse early. Provide
`--cookies` or `youtube.cookies` in config to lift the pause.

## Progress

With `--format text` and `--verbose` a progress bar is rendered on stderr;
`--format json` stays machine-readable (no bar).
