"""Bulk metadata enrichment of pool (scanned, not-synced) items via yt-dlp.

Pool items are YouTube videos discovered by scan whose metadata is thin (e.g.
duration often missing or 0). This module fills them from yt-dlp's own
extractor — no YouTube Data API quota involved.

Shared by `corpus enrich` (commands/enrich) and the corpus_browser webux
plugin so both surfaces behave identically. The yt-dlp call is isolated behind
``fetch_one`` so tests inject a fake instead of hitting the network.

Bot-challenge handling: when YouTube answers "Sign in to confirm you're not a
bot", enrichment pauses immediately (no more yt-dlp calls are submitted) and a
cooldown is persisted so follow-up runs within the window refuse early instead
of hammering the extractor. Provide cookies (--cookies / youtube.cookies in
config) to lift the pause.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from common import structlog

from core.models import SyncFailure
from core.pool_rows import NOT_SYNCED_STATES
from core.sync_errors import BotDetectionError

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

# Bot/captcha challenge markers in yt-dlp error text. Matched case-insensitively;
# when hit, the run is paused instead of retrying every remaining video.
_BOT_CHALLENGE_RE = re.compile(
    r"not a bot|sign in to confirm|verify you'?re human|captcha", re.IGNORECASE
)

_BOT_PAUSE_FILE = "enrich_bot_pause.json"
_DEFAULT_BOT_COOLDOWN_SECONDS = 3600


@dataclass(slots=True)
class EnrichResult:
    """Outcome of one bulk yt-dlp enrichment pass over pool items."""

    source: str
    processed: int = 0  # pool items attempted
    enriched: int = 0  # items whose metadata changed
    skipped: int = 0  # items whose metadata did not change
    failed: int = 0  # items yt-dlp could not fetch
    failures: list[SyncFailure] = field(default_factory=list)
    aborted: bool = False  # True when bot challenge paused the run early
    abort_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "processed": self.processed,
            "enriched": self.enriched,
            "skipped": self.skipped,
            "failed": self.failed,
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "errors": [
                {"source_id": f.source_id, "error": f.error} for f in self.failures
            ],
        }


def _extract_bot_challenge(exc: Exception) -> str | None:
    """Return a human reason if an exception is a YouTube bot challenge."""
    message = str(exc)
    if _BOT_CHALLENGE_RE.search(message):
        return message
    return None


def extract_ytdlp_info(video_id: str, cookies: str | None = None) -> dict:
    """Fetch one video's metadata via yt-dlp (no download, no API quota).

    Returns a flat dict of curated pool-metadata fields. Returns {} when the
    extractor could not produce an info dict (private video without cookies,
    removed video, network issue, ...). Raises BotDetectionError when YouTube
    presents a bot challenge.
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
    }
    if cookies:
        ydl_opts["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        reason = _extract_bot_challenge(exc)
        if reason:
            raise BotDetectionError(
                f"YouTube bot challenge for video {video_id}: {reason}"
            ) from exc
        raise RuntimeError(f"yt-dlp failed for {video_id}: {exc}") from exc

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


def _bot_cooldown_seconds() -> int:
    from common.core.config import load_config

    yt_cfg = load_config().get("youtube", {})
    return int(yt_cfg.get("enrich_bot_cooldown", _DEFAULT_BOT_COOLDOWN_SECONDS))


def _bot_pause_path() -> Any:
    from common.core.paths import get_tool_data_dir

    return get_tool_data_dir("corpus") / _BOT_PAUSE_FILE


def _save_bot_pause(until: datetime) -> None:
    try:
        _bot_pause_path().write_text(
            json.dumps({"paused_at": datetime.now(timezone.utc).isoformat(),
                        "resume_at": until.isoformat()}),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("pool_enrich_pause_write_failed", error=str(exc))


def _load_bot_pause() -> str | None:
    """Return the resume_at ISO timestamp if a bot pause is active, else None."""
    try:
        data = json.loads(_bot_pause_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    resume_at = data.get("resume_at")
    if not resume_at:
        return None
    try:
        resume_dt = datetime.fromisoformat(resume_at)
    except (ValueError, TypeError):
        return None
    if datetime.now(timezone.utc) < resume_dt:
        return resume_at
    return None


def _bot_pause_reason() -> str | None:
    """Pre-run check: why enrichment is currently paused (or None to proceed)."""
    resume_at = _load_bot_pause()
    if resume_at:
        return (
            f"Enrichment is paused: YouTube flagged the IP as a bot. "
            f"Resume after {resume_at}. Provide cookies via `--cookies` or "
            "`youtube.cookies` in config to lift the pause."
        )
    return None


def _run_enrich_loop(
    source: str,
    target_ids: list[str],
    fetch_one: Callable[[str, str | None], dict],
    cookies: str | None,
    concurrency: int,
    progress_cb: Callable[[int, int], None] | None,
    existing_by_id: dict[str, dict],
    writeback: Callable[[str, dict, dict], bool],
) -> EnrichResult:
    """Shared yt-dlp bulk-enrich loop used for pool items and indexed documents.

    For each id, ``fetch_one`` returns the yt-dlp metadata; it is merged over
    the existing metadata (yt-dlp wins, but a 0/None ``duration_seconds`` never
    overwrites a real value) and ``writeback(sid, merged, existing)`` persists
    it, returning True when something changed. On a bot challenge the run
    aborts early and a cooldown is persisted.
    """
    failures: list[SyncFailure] = []
    enriched = skipped = failed = done = 0
    aborted = False
    abort_reason: str | None = None
    total = len(target_ids)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(fetch_one, sid, cookies): sid for sid in target_ids}
        for future in as_completed(futures):
            if aborted:
                future.cancel()
                continue
            sid = futures[future]
            try:
                meta = future.result()
            except BotDetectionError as exc:
                aborted = True
                abort_reason = str(exc)
                _save_bot_pause(
                    datetime.now(timezone.utc) + timedelta(seconds=_bot_cooldown_seconds())
                )
                logger.error("enrich_bot_challenge", video_id=sid, error=str(exc))
                for pending in futures:
                    if not pending.done():
                        pending.cancel()
                continue
            except Exception as exc:  # yt-dlp raised on this single video
                failed += 1
                failures.append(SyncFailure(source_id=sid, error=str(exc)))
                logger.warning("enrich_item_failed", video_id=sid, error=str(exc))
                done += 1
                if progress_cb:
                    progress_cb(done, total)
                continue

            if not meta:
                failed += 1
                failures.append(SyncFailure(source_id=sid, error="no metadata returned"))
                logger.info("enrich_empty", video_id=sid)
                done += 1
                if progress_cb:
                    progress_cb(done, total)
                continue

            existing = existing_by_id.get(sid) or {}
            merged = dict(existing.get("metadata") or {})
            merged.update(meta)
            if not merged.get("duration_seconds") and existing.get("metadata", {}).get("duration_seconds"):
                merged["duration_seconds"] = existing["metadata"]["duration_seconds"]
            if merged == existing.get("metadata"):
                skipped += 1
            elif writeback(sid, merged, existing):
                enriched += 1
                logger.info("enriched", video_id=sid, duration=merged.get("duration_seconds"))
            else:
                skipped += 1
            done += 1
            if progress_cb:
                progress_cb(done, total)

    return EnrichResult(
        source=source,
        processed=done,
        enriched=enriched,
        skipped=skipped,
        failed=failed,
        failures=failures,
        aborted=aborted,
        abort_reason=abort_reason,
    )


def enrich_pool_items(
    store: Any,
    source: str,
    source_ids: list[str] | None = None,
    cookies: str | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    limit: int | None = None,
    fetch_one: Callable[[str, str | None], dict] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> EnrichResult:
    """Bulk-enrich pool (non-synced) items of one source with yt-dlp metadata.

    ``source_ids`` restricts the run to specific pool items; None means every
    non-synced pool item (pending/failed/excluded) of the source. ``limit`` caps
    how many items are attempted (applied after filtering). Metadata is merged
    into the existing pool metadata (yt-dlp wins on conflicts, but a
    ``duration_seconds`` of 0/None never overwrites a real value). Pool status
    and scan date are preserved.

    ``fetch_one`` is the yt-dlp seam: callable(video_id, cookies) -> meta dict.
    ``progress_cb`` (optional) is invoked from the calling thread as
    ``progress_cb(done, total)`` after each item resolves — safe for UI
    progress bars. When a bot challenge is detected the run aborts early,
    future items are cancelled, and ``EnrichResult.aborted`` is set; a cooldown
    is persisted so subsequent runs within the window return paused.
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

    pause_reason = _bot_pause_reason()
    if pause_reason:
        logger.warning("pool_enrich_paused", source=source, reason=pause_reason)
        return EnrichResult(source=source, aborted=True, abort_reason=pause_reason)

    fetch_one = fetch_one or extract_ytdlp_info
    if cookies is None:
        cookies = _config_cookies()

    return _run_enrich_loop(
        source=source,
        target_ids=target_ids,
        fetch_one=fetch_one,
        cookies=cookies,
        concurrency=concurrency,
        progress_cb=progress_cb,
        existing_by_id=pool_by_id,
        writeback=lambda sid, merged, existing: _write_pool_item(store, source, existing, merged),
    )


def _write_pool_item(store: Any, source: str, existing: dict, merged: dict) -> bool:
    store.upsert_pool_item(
        source,
        existing["source_id"],
        existing["status"],
        merged,
        added_at=existing["added_at"],
        synced_at=existing.get("synced_at"),
    )
    return True


def enrich_documents(
    store: Any,
    source: str,
    source_ids: list[str] | None = None,
    cookies: str | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    limit: int | None = None,
    fetch_one: Callable[[str, str | None], dict] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> EnrichResult:
    """Bulk-enrich already-indexed documents of one source with yt-dlp metadata.

    Mirrors :func:`enrich_pool_items` but writes the merged metadata back into
    the documents table (``metadata_json`` plus the ``title`` / ``duration_seconds``
    columns) instead of the scan pool. Content (raw_text / chunks) is untouched,
    so no re-embedding happens. ``source_ids`` restricts to specific documents;
    None means every indexed document of the source.
    """
    doc_by_id: dict[str, dict] = {}
    for row in store.get_documents_raw(source):
        doc = store.get_document(source, row["source_id"])
        if doc is not None:
            doc_by_id[row["source_id"]] = doc

    if source_ids is None:
        target_ids = sorted(doc_by_id.keys())
    else:
        target_ids = [sid for sid in source_ids if sid in doc_by_id]

    if limit is not None:
        target_ids = target_ids[:limit]

    if not target_ids:
        logger.info("doc_enrich_no_items", source=source)
        return EnrichResult(source=source)

    pause_reason = _bot_pause_reason()
    if pause_reason:
        logger.warning("doc_enrich_paused", source=source, reason=pause_reason)
        return EnrichResult(source=source, aborted=True, abort_reason=pause_reason)

    fetch_one = fetch_one or extract_ytdlp_info
    if cookies is None:
        cookies = _config_cookies()

    return _run_enrich_loop(
        source=source,
        target_ids=target_ids,
        fetch_one=fetch_one,
        cookies=cookies,
        concurrency=concurrency,
        progress_cb=progress_cb,
        existing_by_id=doc_by_id,
        writeback=lambda sid, merged, existing: store.update_document_enrichment(source, sid, merged),
    )
