# commands/list/

Implements the `corpus list` CLI command and GET /list API endpoint.

## Purpose
List indexed documents with comprehensive filtering, sorting, and pagination.
Replaces the need for separate get-last command (use --limit 1).

## Features

### Pagination
- `--limit N` — number of items (default: 10)
- `--offset N` — skip first N items (default: 0)
- Example: `--limit 10 --offset 20` gets items 21-30

### Sorting
- `--order-by date` — sort by updated_at (default)
- `--order-by size` — sort by content length (Obsidian)
- `--order-by duration` — sort by video duration (YouTube)
- `--order-by title` — alphabetical
- `--reverse` — reverse sort order (oldest/smallest first)

### Source Filtering
- `--source youtube` — YouTube videos only
- `--source obsidian` — Obsidian notes only
- No flag — all sources

### YouTube-Specific Filters
- `--type short` — videos ≤60s
- `--type long` — videos >60s
- `--min-duration 120` — videos ≥2 minutes
- `--max-duration 600` — videos ≤10 minutes
- `--privacy public` — public videos only
- `--privacy unlisted` — unlisted videos only
- `--privacy private` — private videos only

### Obsidian-Specific Filters
- `--min-size 1000` — notes with ≥1000 characters
- `--max-size 5000` — notes with ≤5000 characters

### Date Filters (All Sources)
- `--since 2024-01-01` — items updated on or after date
- `--until 2024-12-31` — items updated on or before date

### Output Formats
- `--format text` — human-readable (default)
- `--format table` — tabular view with aligned columns
- `--format json` — machine-readable

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
Injects plugin-specific CLI options from both "list" and "search" keys.
