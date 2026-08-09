"""Show pool (scanned, not-indexed) items as browse/list rows.

Pool rows are not real documents: they reuse the doc row shape plus two extra
keys used by the frontend and the CLI. Handles are prefixed so they can never
collide with indexed documents (whose handles are slug-based, never "pool:...").

Shared by `corpus list` (commands/list) and the corpus_browser webux plugin so
that both surfaces agree on row shape, filtering, and sorting.
"""

from __future__ import annotations

from typing import Any

# Pool item statuses that are not indexed yet. "synced" means the item is
# indexed and has a real document — never shown as a pool row.
NOT_SYNCED_STATES = ("pending", "failed", "excluded")

POOL_HANDLE_PREFIX = "pool:"


def pool_row(item: dict[str, Any]) -> dict[str, Any]:
    """Convert a scanned-but-not-synced pool item into a browse/list row."""
    meta = item.get("metadata") or {}
    duration = meta.get("duration_seconds")
    try:
        duration = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    return {
        "handle": f"{POOL_HANDLE_PREFIX}{item['source_plugin']}:{item['source_id']}",
        "source_plugin": item["source_plugin"],
        "source_id": item["source_id"],
        "title": meta.get("title") or item["source_id"],
        "raw_text": None,
        "url": meta.get("url"),
        "updated_at": meta.get("updated_at") or meta.get("published_at"),
        "duration_seconds": duration,
        "privacy_status": meta.get("privacy_status"),
        "metadata": meta,
        "pool_status": item["status"],
        "scan_at": item.get("added_at"),
    }


def pool_matches(row: dict[str, Any], filters) -> bool:
    """Apply the browse filters to a pool row (they have no raw_text/size).

    Duration filters (explicit min/max and the short/long `video_type` filter)
    only apply when the row has a known duration — an item we cannot classify
    is never hidden by a duration filter, so the not-synced queue is not
    silently emptied (e.g. non-video sources carry no duration_seconds).
    """
    if filters is None:
        return True
    duration = row["duration_seconds"]
    if duration is not None:
        if filters.min_duration is not None and duration < filters.min_duration:
            return False
        if filters.max_duration is not None and duration > filters.max_duration:
            return False
    date = row["updated_at"] or ""
    if filters.since and date < f"{filters.since}T00:00:00":
        return False
    if filters.until and date > f"{filters.until}T23:59:59":
        return False
    # missing_field: a pool row has no derived fields yet, so it always matches.
    return True


def select_pool_rows(
    store: Any,
    source: str | None,
    state: str | None,
    filters=None,
) -> list[dict[str, Any]]:
    """Pool rows for one filter state.

    state in {None, "all", "not-synced", "pending", "failed", "excluded"}.
    "synced" (and None) returns no rows: synced items are real documents.
    """
    if state in (None, "synced"):
        return []
    status = None if state in ("all", "not-synced") else state
    items = store.get_pool_items(source, status=status)
    rows = [pool_row(item) for item in items]
    if state in ("all", "not-synced"):
        rows = [row for row in rows if row["pool_status"] in NOT_SYNCED_STATES]
    if filters is not None:
        rows = [row for row in rows if pool_matches(row, filters)]
    return rows


def row_sort_key(row: dict[str, Any], order_by: str):
    """Sort key matching sqlalchemy_store.list_documents_extended ordering."""
    if order_by.startswith("field:"):
        return (row.get("metadata") or {}).get(order_by.split(":", 1)[1])
    if order_by == "size":
        return len(row.get("raw_text") or "") if row.get("raw_text") else -1
    if order_by == "duration":
        return row.get("duration_seconds") or 0
    if order_by == "title":
        return (row.get("title") or "").lower()
    if order_by == "published":
        return (row.get("metadata") or {}).get("published_at") or ""
    return row.get("updated_at") or ""  # date