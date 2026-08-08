from __future__ import annotations

import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()

_TOOL_ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger(__name__)


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


def _scan_source_worker(backend: dict[str, Any], plugin, debug: bool = False):
    """Thin wrapper over core.scan — tests fake quota mid-walk through this."""
    from core.scan import scan_source

    return scan_source(plugin, backend["store"], debug=debug)


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


@router.get("/browse")
def browse(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    min_duration: Optional[int] = Query(None, ge=0),
    max_duration: Optional[int] = Query(None, ge=0),
    order_by: str = Query("date"),
    order_desc: bool = Query(True),
    missing_field: Optional[str] = Query(None),
):
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
        missing_field=missing_field,
    )
    try:
        total = store.count_documents(source=source, filters=filters)
        docs = store.list_documents_extended(
            source=source,
            filters=filters,
            order_by=order_by,
            reverse=not order_desc,
            limit=offset + limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": docs[offset: offset + limit], "total": total}


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