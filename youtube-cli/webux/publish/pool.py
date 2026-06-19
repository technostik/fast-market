from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import DEFAULT_VIDEO_SOURCE_PATH
from .utils import _load_publish_cfg


@dataclass
class PoolItem:
    source: str
    description_prefix: str = ""
    source_urls: list[str] = field(default_factory=list)
    skip_upload: bool = False
    use_groq: bool = False
    status: str = "queued"  # queued | processing | finished | skipped | error
    added_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    job_id: Optional[str] = None  # set when processing starts
    video_url: str = ""
    studio_url: str = ""
    elapsed_seconds: Optional[float] = None
    error_message: str = ""


_pool: list[PoolItem] = []
_pool_state = {"running": False, "current": None}
_worker_task: Optional[asyncio.Task] = None


def _pool_file() -> Path:
    pub = _load_publish_cfg()
    base = Path(pub.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH)).expanduser()
    return base / ".publish-pool.json"


def _load_pool_from_disk():
    global _pool
    p = _pool_file()
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        _pool = [
            PoolItem(
                source=item["source"],
                description_prefix=item.get("description_prefix", ""),
                source_urls=item.get("source_urls", []),
                skip_upload=item.get("skip_upload", False),
                use_groq=item.get("use_groq", False),
                # processing items were interrupted by server restart — reset them
                status="queued" if item.get("status") == "processing" else item.get("status", "queued"),
                added_at=item.get("added_at", time.time()),
                finished_at=item.get("finished_at"),
                video_url=item.get("video_url", ""),
                studio_url=item.get("studio_url", ""),
            )
            for item in data.get("items", [])
        ]
    except Exception:
        pass


def _save_pool_to_disk():
    p = _pool_file()
    data = {
        "items": [
            {
                "source": it.source,
                "description_prefix": it.description_prefix,
                "source_urls": it.source_urls,
                "skip_upload": it.skip_upload,
                "use_groq": it.use_groq,
                "status": it.status,
                "added_at": it.added_at,
                "finished_at": it.finished_at,
                "video_url": it.video_url,
                "studio_url": it.studio_url,
            }
            for it in _pool
        ]
    }
    try:
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _create_meta(source: str, description_prefix: str = "", source_urls: list[str] | None = None):
    meta_path = Path(source).with_name(Path(source).stem + "-meta.json")
    meta = {
        "source": source,
        "description_prefix": description_prefix,
        "source_urls": source_urls or [],
        "status": "queued",
        "added_at": time.time(),
    }
    try:
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:
        pass


def _update_meta_status(source: str, status: str):
    meta_path = Path(source).with_name(Path(source).stem + "-meta.json")
    if not meta_path.exists():
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["status"] = status
        if status in ("finished", "skipped", "error"):
            meta["finished_at"] = time.time()
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:
        pass


def add_to_pool(source: str, description_prefix: str = "", source_urls: list[str] | None = None, skip_upload: bool = False, use_groq: bool = False) -> bool:
    src = str(Path(source).expanduser().resolve())
    if any(item.source == src for item in _pool):
        return False
    source_urls = source_urls or []
    item = PoolItem(source=src, description_prefix=description_prefix, source_urls=source_urls, skip_upload=skip_upload, use_groq=use_groq)
    _pool.append(item)
    _create_meta(src, description_prefix, source_urls)
    _save_pool_to_disk()
    return True


def redo_item(source: str) -> bool:
    src = str(Path(source).expanduser().resolve())
    for it in _pool:
        if it.source == src:
            it.status = "queued"
            it.finished_at = None
            it.elapsed_seconds = None
            it.error_message = ""
            it.job_id = None
            _update_meta_status(src, "queued")
            _save_pool_to_disk()
            start_pool()
            return True
    return False


def remove_from_pool(source: str) -> bool:
    src = str(Path(source).expanduser().resolve())
    global _pool
    before = len(_pool)
    _pool = [it for it in _pool if it.source != src]
    _save_pool_to_disk()
    return len(_pool) < before


def get_pool_state() -> dict:
    # Auto-start the pool worker if there are items to process
    if not _pool_state["running"]:
        has_pending = any(
            it.status == "queued" or it.status == "processing"
            for it in _pool
        )
        if has_pending:
            start_pool()
    items = []
    for it in _pool:
        item_dict = {
            "source": it.source,
            "description_prefix": it.description_prefix,
            "source_urls": it.source_urls,
            "skip_upload": it.skip_upload,
            "status": it.status,
            "added_at": it.added_at,
            "finished_at": it.finished_at,
            "job_id": it.job_id,
            "video_url": it.video_url,
            "studio_url": it.studio_url,
            "elapsed_seconds": it.elapsed_seconds,
            "error_message": it.error_message,
        }
        # If processing and we have a job_id, attach live job status
        if it.job_id and it.status == "processing":
            from .register import _jobs
            job = _jobs.get(it.job_id)
            if job:
                item_dict["job"] = job.to_dict()
        items.append(item_dict)

    return {
        "running": _pool_state["running"],
        "current": _pool_state["current"],
        "items": items,
    }


async def _pool_worker():
    global _pool_state
    while _pool_state["running"]:
        next_item = next((it for it in _pool if it.status == "queued"), None)
        if not next_item:
            await asyncio.sleep(0.2)
            continue

        _pool_state["current"] = next_item.source
        next_item.status = "processing"
        _update_meta_status(next_item.source, "processing")
        _save_pool_to_disk()

        # Create Job and store job_id so UI can show progress
        try:
            from .register import _create_publish_job  # circular-safe

            job = _create_publish_job(
                source=next_item.source,
                description_prefix=next_item.description_prefix,
                source_urls=next_item.source_urls,
                skip_upload=next_item.skip_upload,
                use_groq=next_item.use_groq,
            )
            next_item.job_id = job.job_id
            _save_pool_to_disk()

            from .pipeline import _run_pipeline_from
            await _run_pipeline_from(job, 0)

            if job.status == "error":
                next_item.status = "error"
                next_item.finished_at = time.time()
                if job.start_time:
                    next_item.elapsed_seconds = round(time.time() - job.start_time, 1)
                # Collect error details from the failed step
                for s in job.steps:
                    if s.status == "error" and s.output:
                        next_item.error_message = f"[{s.name}] {s.output}"
                        break
                _update_meta_status(next_item.source, "error")
            else:
                next_item.status = "finished"
                next_item.finished_at = time.time()
                next_item.video_url = job.video_url or ""
                next_item.studio_url = job.studio_url or ""
                if job.end_time and job.start_time:
                    next_item.elapsed_seconds = round(job.end_time - job.start_time, 1)
                elif job.start_time:
                    next_item.elapsed_seconds = round(time.time() - job.start_time, 1)
                _update_meta_status(next_item.source, "finished")
        except Exception as exc:
            next_item.status = "error"
            next_item.finished_at = time.time()
            next_item.error_message = str(exc)
            if 'job' in locals() and job and job.start_time:
                next_item.elapsed_seconds = round(time.time() - job.start_time, 1)
            _update_meta_status(next_item.source, "error")

        _save_pool_to_disk()
        _pool_state["current"] = None
        next_item.job_id = None

        await asyncio.sleep(0.2)

    _pool_state["current"] = None


def start_pool():
    global _worker_task, _pool_state
    if _pool_state["running"]:
        return
    _pool_state["running"] = True
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_pool_worker())


def stop_pool():
    global _pool_state
    _pool_state["running"] = False


def skip_current():
    cur = _pool_state.get("current")
    if not cur:
        return
    for it in _pool:
        if it.source == cur and it.status == "processing":
            it.status = "skipped"
            it.finished_at = time.time()
            _update_meta_status(cur, "skipped")
            _save_pool_to_disk()
            break
    _pool_state["current"] = None


def redo_current():
    cur = _pool_state.get("current")
    target = None
    if cur:
        target = next((it for it in _pool if it.source == cur), None)
    if not target:
        # No current processing item — redo the most recent error item
        target = next((it for it in reversed(_pool) if it.status == "error"), None)
    if not target:
        return
    target.status = "queued"
    target.finished_at = None
    target.elapsed_seconds = None
    target.error_message = ""
    target.job_id = None
    _update_meta_status(target.source, "queued")
    _save_pool_to_disk()
    start_pool()


def clear_finished():
    global _pool
    _pool = [it for it in _pool if it.status != "finished"]
    _save_pool_to_disk()


def find_pool_item(source: str) -> dict | None:
    src = str(Path(source).expanduser().resolve())
    for it in _pool:
        if it.source == src:
            return {
                "source": it.source,
                "description_prefix": it.description_prefix,
                "source_urls": it.source_urls,
                "video_url": it.video_url,
                "studio_url": it.studio_url,
            }
    return None