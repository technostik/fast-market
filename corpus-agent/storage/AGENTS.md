# storage

- Keep code minimal and explicit.
- Use structlog, raise explicit exceptions.

## Sync cursor strategy

Two methods provide cursors for incremental sync:

`get_indexed_ids(source)` → set[str]
  ID-based cursor. Returns all source_ids already in the index for this source.
  Used by YouTube: the plugin walks the playlist newest-first and skips known IDs,
  so each sync fetches the next N unindexed videos regardless of their age.
  DO NOT use date-based cursors for YouTube — published_at of every backlog video
  is older than the newest indexed one, so a date filter silently skips everything
  after the first sync.

`get_latest_content_date(source)` → datetime | None
  Date-based cursor. Returns MAX(updated_at) for the source.
  Used by file-based plugins (Obsidian) where mtime is a reliable incremental cursor.

## privacy_status column

Stored on the `documents` table. Values: "public" | "private" | "unlisted" | "unknown".
Populated by the YouTube plugin. NULL for Obsidian documents.
Exposed in SearchResult, list_documents, and get_document* results.
Filterable via SearchFilters.privacy_status.
