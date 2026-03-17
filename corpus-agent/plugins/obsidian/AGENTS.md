# plugins/obsidian

- Keep code minimal and explicit.
- Use structlog, raise explicit exceptions.

## Recursive scan

`list_items` uses `vault.rglob("*.md")` — all subdirectories are included by default.

## source_id

source_id is the **vault-relative POSIX path** (e.g. `notes/ideas/foo.md`), NOT the
bare filename. This prevents collisions between files with the same name in different
directories, and lets `fetch` reconstruct the full path as `vault / source_id`.

## Exclusions

Directories in `obsidian.exclude_dirs` (config.yaml) are excluded at scan time via
`_is_excluded()`, which checks every path component. Built-in defaults: `.obsidian`,
`.trash`, `.git`. Configurable via `corpus setconfig`.

## Sync cursor

ID + staleness: skip a file only when `source_id in known_id_dates` AND
`mtime <= indexed_updated_at`. A modified file is re-indexed even if already known.
Mtime comparison truncates to second precision to absorb filesystem float rounding.
