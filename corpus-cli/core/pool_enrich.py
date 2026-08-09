"""Bulk metadata enrichment of pool (scanned, not-synced) items via yt-dlp.

Pool items are YouTube videos discovered by scan whose metadata is thin (e.g.
duration often missing or 0). This module fills them from yt-dlp's own
extractor — no YouTube Data API quota involved.

Shared by `corpus enrich` (commands/enrich) and the corpus_browser webux
plugin so both surfaces behave identically. The yt-dlp call is isolated behind
``fetch_one`` so tests inject a fake instead of hitting the network.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from common import structlog

from core.models import SyncFailure
from core.pool_rows import NOT_SYNCED_STATES

logger = structlog.get_logger(__name__)

# Curated map of yt-dlp info keys → pool metadata keys. Only these fields are
# written; the browser auto-surfaces new metadata keys as sortable columns.
_YTDLP_FIELD_MAP: dict[str, Callable[[dict], Any]] = {
    "duration_seconds": lambda info: info.get("duration"),
    "title": lambda info: info.get("title"),
    "description": lambda info: info.get("description"),
    "view_count": lambda info: info.get("view_count"),
    "like_count": lambda info: info.get("like_count"),
    "comment_count": lambda info: info.get("comment_count"),
    "thumbnail": lambda info: info.get("thumbnail"),
    "chapters": lambda info: info.get("chapters"),
    "categories": lambda info: info.get("categories"),
    "tags": lambda info: info.get("tags"),
    "availability": lambda info: info.get("availability"),
    "live_status": lambda info: info.get("live_status"),
    "upload_date": lambda info: info.get("upload_date"),
    "uploader_id": lambda info: info.get("uploader_id"),
    "channel_title": lambda info: info.get("channel"),
}

DEFAULT_CONCURRENCY = 4


@dataclass(slots=True)
class EnrichResult:
    """Outcome of one bulk yt-dlp enrichment pass over pool items."""

    source: str
    processed: int = 0  # pool items attempted
    enriched: int = 0  # items whose metadata changed
    skipped: int = 0  # items whose metadata did not change
    failed: int = 0  # items yt-dlp could not fetch
    failures: list[SyncFailure] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "processed": self.processed,
            "enriched": self.enriched,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": [
                {"source_id": f.source_id, "error": f.error} for f in self.failures
            ],
        }


def extract_ytdlp_info(video_id: str, cookies: str | None = None) -> dict:
    """Fetch one video's metadata via yt-dlp (no download, no API quota).

    Returns a flat dict of curated pool-metadata fields. Returns {} when the
    extractor could not produce an info dict (private video without cookies,
    removed video, network issue, ...).
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("pip install yt-dlp") from exc

    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts: dict = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "no_color": True,
        "ignoreerrors": True,
    }
    if cookies:
        ydl_opts["cookiefile"] = cookies

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        return {}

    meta: dict[str, Any] = {"fetched_at": datetime.now(timezone.utc).isoformat()}
    for key, getter in _YTDLP_FIELD_MAP.items():
        value = getter(info)
        if key == "duration_seconds":
            if not value or int(value) <= 0:
                continue
            meta[key] = int(value)
        elif value is None:
            continue
        else:
            meta[key] = value
    return meta


def _config_cookies() -> str | None:
    from common.core.config import load_config

    yt_cfg = load_config().get("youtube", {})
    return yt_cfg.get("cookies")


def enrich_pool_items(
    store: Any,
    source: str,
    source_ids: list[str] | None = None,
    cookies: str | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    limit: int | None = None,
    fetch_one: Callable[[str, str | None], dict] | None = None,
) -> EnrichResult:
    """Bulk-enrich pool (non-synced) items of one source with yt-dlp metadata.

    ``source_ids`` restricts the run to specific pool items; None means every
    non-synced pool item (pending/failed/excluded) of the source. ``limit`` caps
    how many items are attempted (applied after filtering). Metadata is merged
    into the existing pool metadata (yt-dlp wins on conflicts, but a
    ``duration_seconds`` of 0/None never overwrites a real value). Pool status
    and scan date are preserved.

    ``fetch_one`` is the yt-dlp seam: callable(video_id, cookies) -> meta dict.
    """
    pool_by_id = {item["source_id"]: item for item in store.get_pool_items(source, status=None)}

    if source_ids is None:
        target_ids = sorted(
            sid for sid, item in pool_by_id.items()
            if item["status"] in NOT_SYNCED_STATES
        )
    else:
        target_ids = [sid for sid in source_ids if sid in pool_by_id]

    if limit is not None:
        target_ids = target_ids[:limit]

    if not target_ids:
        logger.info("pool_enrich_no_items", source=source)
        return EnrichResult(source=source)

    fetch_one = fetch_one or extract_ytdlp_info
    if cookies is None:
        cookies = _config_cookies()

    failures: list[SyncFailure] = []
    enriched = skipped = failed = 0

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(fetch_one, sid, cookies): sid for sid in target_ids}
        for future in as_completed(futures):
            sid = futures[future]
            try:
                meta = future.result()
            except Exception as exc:  # yt-dlp raised on this single video
                failed += 1
                failures.append(SyncFailure(source_id=sid, error=str(exc)))
                logger.warning("pool_enrich_item_failed", video_id=sid, error=str(exc))
                continue

            if not meta:
                failed += 1
                failures.append(SyncFailure(source_id=sid, error="no metadata returned"))
                logger.info("pool_enrich_empty", video_id=sid)
                continue

            existing = pool_by_id[sid]
            merged = dict(existing.get("metadata") or {})
            merged.update(meta)
            if not merged.get("duration_seconds") and existing.get("metadata", {}).get("duration_seconds"):
                merged["duration_seconds"] = existing["metadata"]["duration_seconds"]
            if merged == existing.get("metadata"):
                skipped += 1
                continue

            store.upsert_pool_item(
                source,
                sid,
                existing["status"],
                merged,
                added_at=existing["added_at"],
                synced_at=existing.get("synced_at"),
            )
            enriched += 1
            logger.info(
                "pool_enriched",
                video_id=sid,
                duration=merged.get("duration_seconds"),
            )

    return EnrichResult(
        source=source,
        processed=len(target_ids),
        enriched=enriched,
        skipped=skipped,
        failed=failed,
        failures=failures,
    )
