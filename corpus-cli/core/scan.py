from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Scan always attempts to get the full inventory.
# YouTube API caps at 10 pages × 100 videos = 1 000 videos per call.
SCAN_LIMIT = 9999  # effectively "all pages"


@dataclass(slots=True)
class ScanSummary:
    """Outcome of walking one source's full inventory into the sync pool."""

    source: str
    processed: int = 0  # items walked (added + refreshed)
    added: int = 0  # genuinely new pool items
    refreshed: int = 0  # existing items whose pool metadata changed
    requeued: int = 0  # failed pool items reset to pending (state change)
    pool_pending: int = 0
    pool_synced: int = 0
    pool_failed: int = 0
    pool_excluded: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "processed": self.processed,
            "added": self.added,
            "refreshed": self.refreshed,
            "requeued": self.requeued,
            "pool": {
                "pending": self.pool_pending,
                "synced": self.pool_synced,
                "failed": self.pool_failed,
                "excluded": self.pool_excluded,
            },
        }


def scan_source(plugin, store, debug: bool = False) -> ScanSummary:
    """Generic full-inventory scan for any plugin whose list_items supports
    scan_all=True.

    Adds genuinely new items to the pool as 'pending' and refreshes the pool
    metadata of existing pending/failed items so status changes are detected.
    Synced/excluded/indexed IDs are passed as 'known' so the plugin skips them.

    Plugins that re-queue on a state change (e.g. YouTube: a 'failed' item that
    became 'public' is reset to 'pending') can declare `requeue_on` describing
    the new-state value; defaults to nothing.

    Raises the plugin's own errors (e.g. APIRateLimitError) — callers decide
    how to surface them.
    """
    import inspect

    # Load current pool and document state upfront
    all_pool = store.get_pool_items(plugin.name, status=None)
    pool_by_id: dict[str, dict] = {item["source_id"]: item for item in all_pool}
    indexed_ids: set[str] = set(store.get_indexed_id_dates(plugin.name).keys())

    # Pass synced/excluded/indexed IDs as "known" so the API skips them.
    # pending/failed IDs are NOT in known → the API returns them so we can
    # refresh their metadata.
    skip_ids: set[str] = (
        {sid for sid, item in pool_by_id.items() if item["status"] in ("synced", "excluded")}
        | indexed_ids
    )
    known_id_dates = {sid: None for sid in skip_ids}

    list_kwargs: dict = {
        "limit": SCAN_LIMIT,
        "known_id_dates": known_id_dates,
        "scan_all": True,
        "debug": debug,
    }
    # scan_all is the new param; fall back gracefully if the plugin doesn't have it yet
    sig = inspect.signature(plugin.list_items)
    if "scan_all" not in sig.parameters:
        raise TypeError(
            f"scan: plugin '{plugin.name}' has no scan_all discovery path"
        )

    items = plugin.list_items(**list_kwargs)

    now = datetime.utcnow().isoformat()
    processed = added = refreshed = requeued = 0

    # Plugin hook: which metadata state change re-queues a failed pool item.
    requeue_on = getattr(plugin, "requeue_on", None)

    for item in items:
        sid = item.source_id
        new_meta = _item_meta(item)

        if sid in pool_by_id:
            existing = pool_by_id[sid]
            pool_status = existing["status"]

            if existing.get("metadata") != new_meta:
                # Metadata changed — update metadata in pool
                store.upsert_pool_item(
                    plugin.name, sid, pool_status,
                    new_meta,
                    added_at=existing["added_at"],
                )
                refreshed += 1
                # Re-queue failed items whose state changed to the requeue-on
                # state (e.g. YouTube: failed → now public → pending).
                if pool_status == "failed" and requeue_on and new_meta.get(
                    "privacy_status"
                ) == requeue_on:
                    store.mark_pool_item(plugin.name, sid, "pending")
                    requeued += 1
        elif sid not in indexed_ids:
            # Genuinely new item — not yet in pool or indexed
            store.upsert_pool_item(plugin.name, sid, "pending", new_meta, added_at=now)
            added += 1

    pool_stats = store.pool_stats()
    src_pool = next(
        (p for p in pool_stats if p["source_plugin"] == plugin.name), {}
    )
    return ScanSummary(
        source=plugin.name,
        processed=added + refreshed,
        added=added,
        refreshed=refreshed,
        requeued=requeued,
        pool_pending=int(src_pool.get("pending", 0)),
        pool_synced=int(src_pool.get("synced", 0)),
        pool_failed=int(src_pool.get("failed", 0)),
        pool_excluded=int(src_pool.get("excluded", 0)),
    )


def _item_meta(item) -> dict:
    """Pool metadata for an ItemMeta — always includes updated_at so
    sync_pool_items can reconstruct the publication date from the pool."""
    meta = dict(item.metadata or {})
    if item.updated_at and "updated_at" not in meta:
        meta["updated_at"] = item.updated_at.isoformat()
    return meta