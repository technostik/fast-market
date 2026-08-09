from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from common import structlog

from core.pool_enrich import EnrichResult

router = APIRouter()

_TOOL_ROOT = Path(__file__).resolve().parents[2]

logger = structlog.get_logger(__name__)


# ─── In-memory background job registry ────────────────────────────────────────
#
# Jobs (scan / field sync) can run for minutes, far beyond a synchronous HTTP
# request timeout. State is kept in a process-local dict: it is transient
# process state, not durable business data — no SQL table. Known limitation:
# job state does not survive a server restart (acceptable for this use case).
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job(kind: str, payload: dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "kind": kind,
            "status": "running",
            "created_at": _now_iso(),
            "finished_at": None,
            "payload": payload,
            "result": None,
            "error": None,
        }
    return job_id


def _get_job(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _update_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(fields)


def _job_response(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return {
        "job_id": job_id,
        "kind": job.get("kind"),
        "status": job.get("status"),
        "result": job.get("result"),
        "error": job.get("error"),
    }


# ─── error mapping: structured, never inferred from error strings ────────────


def _map_error(exc: Exception) -> dict[str, Any]:
    from core.sync_errors import APIRateLimitError

    if isinstance(exc, APIRateLimitError):
        return {
            "type": "quota_exceeded",
            "message": str(exc),
            "quota_reset_at": exc.quota_reset_at,
        }
    return {"type": "unknown", "message": str(exc)}


# ─── backend seam ─────────────────────────────────────────────────────────────

_BACKEND_CACHE: dict[str, dict[str, Any]] = {}


def _backend_factory() -> dict[str, Any]:
    """Build (and cache per db file) the corpus backend for one process.

    Heavy imports live here so handlers stay lazy. Tests replace this
    function wholesale with fakes.
    """
    from common.core.config import load_config
    from common.core.registry import build_plugins
    from core.embedder import Embedder
    from core.sync_engine import SyncEngine
    from storage.sqlalchemy_store import SQLAlchemyStore

    config = load_config()
    cache_key = f"file:{config.get('db_path')}" if config.get("db_path") else "default"
    cached = _BACKEND_CACHE.get(cache_key)
    if cached is not None:
        return cached

    store = SQLAlchemyStore(config.get("db_path"))
    plugins = build_plugins(config, tool_root=_TOOL_ROOT)
    engine = SyncEngine(
        store, Embedder(batch_size=int(config.get("embed_batch_size", 32)))
    )
    backend = {
        "config": config,
        "store": store,
        "engine": engine,
        "plugins": plugins,
    }
    _BACKEND_CACHE[cache_key] = backend
    return backend


def _discover_operations() -> dict[str, Any]:
    from common.core.registry import discover_operations

    return discover_operations(_backend_factory()["config"], tool_root=_TOOL_ROOT)


def _operation_list() -> list[dict[str, Any]]:
    ops = _discover_operations()
    return [
        {"name": m.name, "field": m.field, "applies_to": m.applies_to}
        for m in sorted(ops.values(), key=lambda m: m.name)
        if m.field
    ]


def _scan_source_worker(store: Any, plugin, debug: bool = False):
    """Thin wrapper over core.scan — tests fake quota mid-walk through this."""
    from core.scan import scan_source

    return scan_source(plugin, store, debug=debug)


def _enrich_worker(store: Any, source: str, **kwargs):
    """Thin wrapper over core.pool_enrich — tests replace this wholesale."""
    from core.pool_enrich import enrich_pool_items

    return enrich_pool_items(store, source, **kwargs)


def _enrich_docs_worker(store: Any, source: str, **kwargs):
    """Thin wrapper over core.pool_enrich.enrich_documents — tests replace this."""
    from core.pool_enrich import enrich_documents

    return enrich_documents(store, source, **kwargs)


# ─── API: fields, operations, sources ─────────────────────────────────────────


@router.get("/fields")
def fields(
    source: Optional[str] = Query(None, description="Filter fields by source plugin"),
):
    """Field definitions applicable to a source (or the common ones for "all")."""
    all_fields = _backend_factory()["store"].list_field_definitions()
    if source:
        applicable = [f for f in all_fields if f.get("applies_to") in ("all", source)]
    else:
        applicable = [f for f in all_fields if f.get("applies_to") == "all"]
    return {"source": source, "fields": applicable}


@router.get("/operations")
def operations():
    """Registered field-producing operations for bulk actions (derived fields)."""
    return {"operations": _operation_list()}


@router.get("/sources")
def get_sources():
    backend = _backend_factory()
    known = set(backend["store"].list_sources())
    try:
        known |= set(backend["plugins"].keys())
    except Exception:
        # Plugin misconfiguration must not break the read-only sources listing.
        logger.warning("plugin_discovery_failed_for_sources", exc_info=True)
    return {"sources": sorted(known)}


# ─── browse / search / document / stats ───────────────────────────────────────

# Pool rows (scanned but not yet indexed) reuse the doc row shape; the row
# conversion, filtering and sorting live in core.pool_rows, shared with the CLI.
from core.pool_rows import select_pool_rows

# Metadata keys already surfaced as first-class columns — never repeated as
# extra per-source columns.
_CORE_META_COLUMNS = {
    "id", "title", "url", "duration_seconds", "published_at", "updated_at",
}


def _source_extra_meta_keys(store: Any, source: str) -> set[str]:
    """Metadata keys present on docs/pool items of one source (column candidates)."""
    keys: set[str] = set()
    try:
        docs = store.list_documents_extended(
            source=source, order_by="date", limit=120
        )
        for doc in docs:
            keys |= set(doc.get("metadata", {}).keys())
    except Exception as exc:  # malformed metadata must not break the column list
        logger.warning("extra_meta_keys_scan_failed", error=str(exc))
    try:
        for item in store.get_pool_items(source, status=None):
            keys |= set((item.get("metadata") or {}).keys())
    except Exception as exc:
        logger.warning("extra_meta_keys_pool_failed", error=str(exc))
    return keys - _CORE_META_COLUMNS


@router.get("/columns")
def columns(
    source: Optional[str] = Query(None, description="Columns for one source, or common ones"),
):
    """Extra table columns.

    Without a source: only common declared fields (applies_to=all).
    With a source: all declared fields applicable to that source plus every
    metadata key this source's plugin stores (documents + scanned pool).
    """
    all_fields = _backend_factory()["store"].list_field_definitions()
    if source:
        applicable = [f for f in all_fields if f.get("applies_to") in ("all", source)]
        declared = [{"name": f["name"], "kind": "field"} for f in applicable]
        meta_keys = sorted(_source_extra_meta_keys(_backend_factory()["store"], source))
        return {
            "source": source,
            "columns": [{"name": k, "kind": "meta"} for k in meta_keys] + declared,
        }
    common = [f for f in all_fields if f.get("applies_to") == "all"]
    return {"source": None, "columns": [{"name": f["name"], "kind": "field"} for f in common]}


# ─── column visibility prefs, persisted in the corpus tool config ─────────────
#
# The browser stores which fixed columns / dynamic fields are hidden in the
# tool config (browser_columns key) so the selection survives sessions and is
# shared across devices/terminals, not locked to one browser's localStorage.

_COLUMN_PREFS_KEY = "browser_columns"


def _column_prefs_path() -> Path:
    from common.core.config import get_tool_config_path

    return get_tool_config_path("corpus")


def _read_raw_tool_config() -> dict[str, Any]:
    import yaml

    path = _column_prefs_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("corpus_browser_tool_config_unreadable", error=str(exc))
        return {}
    return data if isinstance(data, dict) else {}


def _read_column_prefs() -> dict[str, list[str]]:
    prefs = _read_raw_tool_config().get(_COLUMN_PREFS_KEY) or {}
    if not isinstance(prefs, dict):
        prefs = {}
    return {
        "fixedOff": [str(k) for k in prefs.get("fixedOff", []) if isinstance(k, str)],
        "fieldsOff": [str(k) for k in prefs.get("fieldsOff", []) if isinstance(k, str)],
    }


def _write_column_prefs(fixed_off: list[str], fields_off: list[str]) -> None:
    from common.core.yaml_utils import dump_yaml

    data = _read_raw_tool_config()
    data[_COLUMN_PREFS_KEY] = {"fixedOff": list(fixed_off), "fieldsOff": list(fields_off)}
    _column_prefs_path().write_text(dump_yaml(data, sort_keys=False), encoding="utf-8")


class _ColumnPrefsBody(BaseModel):
    fixedOff: list[str] = []
    fieldsOff: list[str] = []


@router.get("/columns/prefs")
def get_column_prefs() -> dict[str, list[str]]:
    """Hidden columns, persisted in the corpus tool config."""
    return _read_column_prefs()


@router.post("/columns/prefs")
def save_column_prefs(body: _ColumnPrefsBody) -> dict[str, bool]:
    """Persist hidden columns in the corpus tool config."""
    _write_column_prefs(body.fixedOff, body.fieldsOff)
    return {"ok": True}


def _count_shorts_hidden(
    store: Any,
    source: str | None,
    state: str | None,
    video_type: str | None,
) -> int:
    """Count pool candidates the short/long filter hides (known durations only)."""
    from core.pool_rows import select_pool_rows
    from storage.sqlalchemy_store import SearchFilters, YOUTUBE_SHORT_MAX_SECONDS

    if video_type not in ("short", "long") or state == "synced":
        return 0
    no_short_filter = SearchFilters(source=source, video_type=None)
    rows = select_pool_rows(store, source, state or "all", no_short_filter)
    if video_type == "long":
        return sum(1 for r in rows if (r["duration_seconds"] or 0) <= YOUTUBE_SHORT_MAX_SECONDS)
    return sum(1 for r in rows if (r["duration_seconds"] or 0) > YOUTUBE_SHORT_MAX_SECONDS)


@router.get("/browse")
def browse(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    min_duration: Optional[int] = Query(None, ge=0),
    max_duration: Optional[int] = Query(None, ge=0),
    video_type: Optional[str] = Query(None, pattern="^(short|long)$"),
    order_by: str = Query("date"),
    order_desc: bool = Query(True),
    missing_field: Optional[str] = Query(None),
    state: Optional[str] = Query(
        None,
        pattern="^(all|synced|not-synced|pending|failed|excluded)$",
        description="Which pool state to show: all (default), synced (indexed "
        "docs only), not-synced (pending/failed/excluded), or one state.",
    ),
):
    from core.pool_rows import row_sort_key
    from storage.sqlalchemy_store import SearchFilters

    if order_by.startswith("field:"):
        field_name = order_by.split(":", 1)[1]
        if not re.fullmatch(r"[a-z][a-z0-9_]*", field_name):
            raise HTTPException(
                status_code=400, detail=f"Invalid field name in order_by: {field_name}"
            )

    backend = _backend_factory()
    store = backend["store"]
    filters = SearchFilters(
        source=source,
        since=since,
        until=until,
        min_duration=min_duration,
        max_duration=max_duration,
        video_type=video_type,
        missing_field=missing_field,
    )
    try:
        # Docs are only merged in for the "all"/"synced" views. The pending /
        # failed / excluded / not-synced states show the sync queue only, so
        # they stay consistent with `corpus list --state ...`.
        docs = []
        if state in (None, "all", "synced"):
            docs = store.list_documents_extended(
                source=source,
                filters=filters,
                order_by=order_by,
                reverse=not order_desc,
                limit=200000,
            )
        # "View all" (no state / state=all) shows indexed documents AND every
        # not-synced pool item in one merged table.
        pool_rows = select_pool_rows(store, source, state or "all", filters)
        # How many pool candidates the short/long filter hid (explains an empty
        # queue: "everything pending is a Short").
        shorts_hidden = _count_shorts_hidden(store, source, state, video_type)
        total = len(docs) + len(pool_rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    rows = docs + pool_rows
    rows.sort(key=lambda r: row_sort_key(r, order_by), reverse=order_desc)
    return {"items": rows[offset: offset + limit], "total": total, "shorts_hidden": shorts_hidden}


@router.get("/search")
def search(
    q: str = Query(""),
    mode: str = Query("keyword", pattern="^(keyword|semantic)$"),
    limit: int = Query(500, ge=1, le=500),
    source: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    min_duration: Optional[int] = Query(None, ge=0),
    max_duration: Optional[int] = Query(None, ge=0),
    video_type: Optional[str] = Query(None, pattern="^(short|long)$"),
):
    from core.embedder import Embedder
    from storage.sqlalchemy_store import SearchFilters

    store = _backend_factory()["store"]
    filters = SearchFilters(
        source=source,
        since=since,
        until=until,
        min_duration=min_duration,
        max_duration=max_duration,
        video_type=video_type,
    )

    if not q.strip():
        return {"query": q, "mode": mode, "results": []}

    if mode == "semantic":
        embedder = Embedder()
        vector = embedder.embed_texts([q])[0][1]
        results = store.semantic_search(vector, limit=limit, filters=filters)
    else:
        results = store.keyword_search(q, limit=limit, filters=filters)

    return {
        "query": q,
        "mode": mode,
        "results": [
            {
                "handle": r.handle,
                "source_plugin": r.source_plugin,
                "source_id": r.source_id,
                "title": r.title,
                "excerpt": r.excerpt,
                "score": r.score,
                "duration": r.duration_seconds,
            }
            for r in results
        ],
    }


@router.get("/document/{handle}")
def show_document(handle: str):
    store = _backend_factory()["store"]
    doc = store.get_document_by_handle(handle)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/stats")
def stats():
    return {"stats": _backend_factory()["store"].status()}


# ─── POST /scan + GET /scan/status ────────────────────────────────────────────


class _ScanRequest(BaseModel):
    source: str = "all"


@router.post("/scan")
def start_scan(req: _ScanRequest, background_tasks: BackgroundTasks):
    plugins = _backend_factory()["plugins"]
    if req.source != "all" and req.source not in plugins:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source plugin: {req.source}. Available: {sorted(plugins)}",
        )
    job_id = _new_job("scan", {"source": req.source})
    background_tasks.add_task(_run_scan_job, job_id)
    return {"job_id": job_id, "status": "running", "source": req.source}


@router.get("/scan/status/{job_id}")
def scan_status(job_id: str):
    """running|done|error.

    error.type == "quota_exceeded" carries quota_reset_at; every other failure
    is error.type == "unknown" with the raw message. Partial results are kept
    in `result` so interrupted runs report their processed count.
    """
    return _job_response(job_id)


def _run_scan_job(job_id: str) -> None:
    payload = _get_job(job_id).get("payload", {})
    source_req = payload.get("source", "all")
    result: dict[str, Any] = {
        "source": source_req,
        "per_source": [],
        "processed": 0,
        "added": 0,
        "refreshed": 0,
        "requeued": 0,
    }
    try:
        backend = _backend_factory()
        plugins = backend["plugins"]
        sources = sorted(plugins) if source_req == "all" else [source_req]
        for name in sources:
            summary = _scan_source_worker(backend["store"], plugins[name])
            data = summary.to_dict()
            result["per_source"].append(data)
            result["processed"] += int(data.get("processed", 0))
            result["added"] += int(data.get("added", 0))
            result["refreshed"] += int(data.get("refreshed", 0))
            result["requeued"] += int(data.get("requeued", 0))
            # Partial progress is persisted so a later failure keeps the counts.
            _update_job(job_id, result=result)
        _update_job(job_id, status="done", result=result, finished_at=_now_iso())
    except Exception as exc:
        logger.exception("corpus_browser_scan_job_failed", job_id=job_id, source=source_req)
        _update_job(job_id, status="error", error=_map_error(exc), result=result)


# ─── POST /enrich + GET /enrich/status (yt-dlp pool metadata enrichment) ─────


class _EnrichRequest(BaseModel):
    source: Optional[str] = None
    handles: Optional[list[str]] = None
    limit: Optional[int] = None
    concurrency: int = 4


@router.post("/enrich")
def start_enrich(req: _EnrichRequest, background_tasks: BackgroundTasks):
    """Bulk-fill metadata (duration, views, tags, ...) via yt-dlp — no YouTube
    API quota involved. Mirrors `corpus enrich`.

    Without ``handles`` it targets every non-synced pool item of the source.
    With ``handles`` it enriches the selected items regardless of sync state:
    ``pool:<source>:<id>`` handles address pool (not-synced) items, any other
    handle (a document handle) addresses an already-indexed document."""
    backend = _backend_factory()
    plugins = backend["plugins"]
    source = req.source
    if source is None:
        # Mirror `corpus enrich`: default to the YouTube plugin when present,
        # else the first plugin (enrichment is yt-dlp/YouTube specific).
        source = "youtube" if "youtube" in plugins else next(iter(plugins), None)
    if source and source not in plugins:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source plugin: {source}. "
                   f"Available: {sorted(plugins)}",
        )
    payload = {
        "source": source,
        "handles": req.handles,
        "limit": req.limit,
        "concurrency": req.concurrency or 4,
    }
    job_id = _new_job("enrich", payload)
    background_tasks.add_task(_run_enrich_job, job_id)
    return {"job_id": job_id, "status": "running", "source": source}


@router.get("/enrich/status/{job_id}")
def enrich_status(job_id: str):
    return _job_response(job_id)


def _partition_enrich_handles(store: Any, source: str, handles: list[str]) -> tuple[list[str], list[str]]:
    """Split enrich handles into pool source_ids and document source_ids.

    ``pool:<source>:<id>`` handles map to pool (not-synced) items; any other
    handle is looked up as an indexed document of the requested source.
    """
    pool_ids: list[str] = []
    doc_ids: list[str] = []
    for h in handles:
        if h.startswith(f"pool:{source}:") and len(h.split(":", 2)) == 3:
            pool_ids.append(h.split(":", 2)[2])
        else:
            doc = store.get_document_by_handle(h)
            if doc and doc.get("source_plugin") == source:
                doc_ids.append(doc["source_id"])
    return pool_ids, doc_ids


def _merge_enrich_results(source: str, *results: EnrichResult) -> EnrichResult:
    merged = EnrichResult(source=source)
    for res in results:
        merged.processed += res.processed
        merged.enriched += res.enriched
        merged.skipped += res.skipped
        merged.failed += res.failed
        merged.failures += res.failures
        if res.aborted:
            merged.aborted = True
            merged.abort_reason = merged.abort_reason or res.abort_reason
    return merged


def _run_enrich_job(job_id: str) -> None:
    payload = _get_job(job_id).get("payload", {})
    result: dict[str, Any] | None = None
    try:
        backend = _backend_factory()
        store = backend["store"]
        source = payload.get("source")
        if not source:
            raise HTTPException(
                status_code=400,
                detail="No source plugin available to enrich.",
            )
        concurrency = int(payload.get("concurrency") or 4)
        handles = payload.get("handles")
        if handles:
            pool_ids, doc_ids = _partition_enrich_handles(store, source, handles)
            if not pool_ids and not doc_ids:
                raise HTTPException(
                    status_code=400,
                    detail="No pool or synced handles matched the requested source.",
                )
            pool_result = _enrich_worker(store, source, source_ids=pool_ids, concurrency=concurrency)
            doc_result = _enrich_docs_worker(store, source, source_ids=doc_ids, concurrency=concurrency)
        else:
            # Bulk "Enrich all": non-synced pool items only (unchanged behaviour).
            pool_result = _enrich_worker(
                store, source, source_ids=None, limit=payload.get("limit"),
                concurrency=concurrency,
            )
            doc_result = EnrichResult(source=source)
        summary = _merge_enrich_results(source, pool_result, doc_result)
        result = summary.to_dict()
        _update_job(job_id, status="done", result=result, finished_at=_now_iso())
    except Exception as exc:
        logger.exception("corpus_browser_enrich_job_failed", job_id=job_id, source=payload.get("source"))
        _update_job(job_id, status="error", error=_map_error(exc), result=result)


# ─── POST /sync-pool + GET /sync-pool/status (index selected pool items) ──────


class _SyncPoolRequest(BaseModel):
    source: str
    handles: list[str]


@router.post("/sync-pool")
def start_sync_pool(req: _SyncPoolRequest, background_tasks: BackgroundTasks):
    """Fetch and index the given not-synced pool items into the corpus.
    ``handles`` are pool handles (pool:<source>:<id>). Syncing a pool item is
    an operation like any other: select videos in the browser, then Sync."""
    backend = _backend_factory()
    if req.source not in backend["plugins"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source plugin: {req.source}. "
                   f"Available: {sorted(backend['plugins'])}",
        )
    if not req.handles:
        raise HTTPException(status_code=400, detail="No pool handles provided.")
    payload = {"source": req.source, "handles": req.handles}
    job_id = _new_job("sync-pool", payload)
    background_tasks.add_task(_run_sync_pool_job, job_id)
    return {"job_id": job_id, "status": "running", "source": req.source}


@router.get("/sync-pool/status/{job_id}")
def sync_pool_status(job_id: str):
    return _job_response(job_id)


def _sync_pool_worker(store: Any, engine: Any, plugin, pool_items, vault_path=None):
    """Thin wrapper over SyncEngine.sync_pool_items — tests replace this."""
    return engine.sync_pool_items(plugin, pool_items, vault_path=vault_path)


def _run_sync_pool_job(job_id: str) -> None:
    payload = _get_job(job_id).get("payload", {})
    result: dict[str, Any] | None = None
    try:
        backend = _backend_factory()
        store = backend["store"]
        source = payload["source"]
        wanted = set(payload.get("handles") or [])
        pool_items = [
            i for i in store.get_pool_items(source, status=None)
            if f"pool:{source}:{i['source_id']}" in wanted
        ]
        if not pool_items:
            raise HTTPException(
                status_code=400,
                detail="None of the given handles matched pool items.",
            )
        sync_result = _sync_pool_worker(
            backend["store"],
            backend["engine"],
            backend["plugins"][source],
            pool_items,
            vault_path=None,
        )
        result = {
            "source": sync_result.source,
            "processed": sync_result.processed,
            "indexed": sync_result.indexed,
            "skipped": sync_result.skipped,
            "failures": [
                {"source_id": f.source_id, "error": f.error}
                for f in sync_result.failures
            ],
            "warning": sync_result.warning,
        }
        _update_job(job_id, status="done", result=result, finished_at=_now_iso())
    except Exception as exc:
        logger.exception(
            "corpus_browser_sync_pool_job_failed",
            job_id=job_id,
            source=payload.get("source"),
        )
        _update_job(job_id, status="error", error=_map_error(exc), result=result)


# ─── POST /resync + GET /resync/status (re-fetch transcripts of synced docs) ──


class _ResyncRequest(BaseModel):
    source: str
    handles: list[str]


@router.post("/resync")
def start_resync(req: _ResyncRequest, background_tasks: BackgroundTasks):
    """Re-fetch the content (transcript) of already-indexed documents.

    ``handles`` are document handles (not pool handles). Documents whose content
    changed are re-chunked and re-embedded; unchanged ones are skipped. Stored
    metadata is preserved."""
    backend = _backend_factory()
    if req.source not in backend["plugins"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source plugin: {req.source}. "
                   f"Available: {sorted(backend['plugins'])}",
        )
    if not req.handles:
        raise HTTPException(status_code=400, detail="No document handles provided.")
    job_id = _new_job("resync", {"source": req.source, "handles": req.handles})
    background_tasks.add_task(_run_resync_job, job_id)
    return {"job_id": job_id, "status": "running", "source": req.source}


@router.get("/resync/status/{job_id}")
def resync_status(job_id: str):
    return _job_response(job_id)


def _run_resync_job(job_id: str) -> None:
    payload = _get_job(job_id).get("payload", {})
    result: dict[str, Any] | None = None
    try:
        backend = _backend_factory()
        source = payload["source"]
        sync_result = backend["engine"].sync_documents(
            backend["plugins"][source], payload.get("handles") or []
        )
        result = {
            "source": sync_result.source,
            "processed": sync_result.processed,
            "indexed": sync_result.indexed,
            "skipped": sync_result.skipped,
            "failures": [
                {"source_id": f.source_id, "error": f.error}
                for f in sync_result.failures
            ],
            "warning": sync_result.warning,
        }
        _update_job(job_id, status="done", result=result, finished_at=_now_iso())
    except Exception as exc:
        logger.exception(
            "corpus_browser_resync_job_failed",
            job_id=job_id,
            source=payload.get("source"),
        )
        _update_job(job_id, status="error", error=_map_error(exc), result=result)


# ─── POST /sync + GET /sync/status (reuses SyncEngine.sync_field) ─────────────


class _SyncRequest(BaseModel):
    field: str
    source: Optional[str] = None
    handles: Optional[list[str]] = None
    limit: Optional[int] = None
    since: Optional[str] = None
    until: Optional[str] = None
    min_duration: Optional[int] = None
    max_duration: Optional[int] = None


@router.post("/sync")
def start_sync(req: _SyncRequest, background_tasks: BackgroundTasks):
    backend = _backend_factory()
    store = backend["store"]
    if not store.get_field_definition(req.field):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Field '{req.field}' is not declared. Declare it with "
                "`corpus field create` first."
            ),
        )
    if not any(op["field"] == req.field for op in _operation_list()):
        raise HTTPException(
            status_code=400,
            detail=f"No registered operation produces field '{req.field}'.",
        )
    if req.source and req.source != "all":
        if req.source not in backend["plugins"]:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown source plugin: {req.source}. "
                       f"Available: {sorted(backend['plugins'])}",
            )

    payload = {
        "field": req.field,
        "source": req.source,
        "handles": req.handles,
        "limit": req.limit,
        "since": req.since,
        "until": req.until,
        "min_duration": req.min_duration,
        "max_duration": req.max_duration,
    }
    job_id = _new_job("sync", payload)
    background_tasks.add_task(_run_sync_job, job_id)
    return {"job_id": job_id, "status": "running", "field": req.field}


@router.get("/sync/status/{job_id}")
def sync_status(job_id: str):
    return _job_response(job_id)


def _run_sync_job(job_id: str) -> None:
    from storage.sqlalchemy_store import SearchFilters

    payload = _get_job(job_id).get("payload", {})
    result: dict[str, Any] | None = None
    try:
        backend = _backend_factory()
        manifest = next(
            (m for m in _discover_operations().values()
             if m.field == payload.get("field")),
            None,
        )
        if manifest is None:
            raise HTTPException(
                status_code=400,
                detail=f"No registered operation produces field '{payload['field']}'.",
            )
        operation = manifest.operation_class(backend["config"])
        filters = SearchFilters(
            since=payload.get("since"),
            until=payload.get("until"),
            min_duration=payload.get("min_duration"),
            max_duration=payload.get("max_duration"),
        )
        source = None if payload.get("source") in (None, "all") else payload["source"]
        sync_result = backend["engine"].sync_field(
            payload["field"],
            operation,
            source=source,
            limit=payload.get("limit") or 1000,
            handles=payload.get("handles"),
            filters=filters,
        )
        result = {
            "field": payload["field"],
            "source": source,
            "processed": sync_result.processed,
            "indexed": sync_result.indexed,
            "skipped": sync_result.skipped,
            "failures": [
                {"source_id": f.source_id, "error": f.error}
                for f in sync_result.failures
            ],
            "warning": sync_result.warning,
        }
        _update_job(job_id, status="done", result=result, finished_at=_now_iso())
    except Exception as exc:
        logger.exception(
            "corpus_browser_sync_job_failed",
            job_id=job_id,
            field=payload.get("field"),
        )
        _update_job(job_id, status="error", error=_map_error(exc), result=result)


_HTML = (Path(__file__).parent / "frontend.html").read_text(encoding="utf-8")


def register(config: dict) -> WebuxPluginManifest:
    from common.webux.base import WebuxPluginManifest
    del config
    return WebuxPluginManifest(
        name="corpus_browser",
        tab_label="Corpus Browser",
        tab_icon="🔍",
        api_router=router,
        frontend_html=_HTML,
        order=20,
        lazy=True,
    )