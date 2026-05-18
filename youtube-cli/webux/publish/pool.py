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
    skip_upload: bool = False
    status: str = "queued"  # queued | processing | finished | skipped | error
    added_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    job_id: Optional[str] = None  # set when processing starts
    video_url: str = ""
    studio_url: str = ""


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
                status=item.get("status", "queued"),
                added_at=item.get("added_at", time.time()),
                finished_at=item.get("finished_at"),
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
                "status": it.status,
                "added_at": it.added_at,
                "finished_at": it.finished_at,
            }
            for it in _pool
        ]
    }
    try:
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _create_meta(source: str, description_prefix: str):
    meta_path = Path(source).with_name(Path(source).stem + "-meta.json")
    meta = {
        "source": source,
        "description_prefix": description_prefix,
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


def add_to_pool(source: str, description_prefix: str = "", skip_upload: bool = False) -> bool:
    src = str(Path(source).expanduser().resolve())
    if any(item.source == src for item in _pool):
        return False
    item = PoolItem(source=src, description_prefix=description_prefix, skip_upload=skip_upload)
    _pool.append(item)
    _create_meta(src, description_prefix)
    _save_pool_to_disk()
    return True


def remove_from_pool(source: str) -> bool:
    src = str(Path(source).expanduser().resolve())
    global _pool
    before = len(_pool)
    _pool = [it for it in _pool if it.source != src]
    _save_pool_to_disk()
    return len(_pool) < before


def get_pool_state() -> dict:
    items = []
    for it in _pool:
        item_dict = {
            "source": it.source,
            "description_prefix": it.description_prefix,
            "skip_upload": it.skip_upload,
            "status": it.status,
            "added_at": it.added_at,
            "finished_at": it.finished_at,
            "job_id": it.job_id,
            "video_url": it.video_url,
            "studio_url": it.studio_url,
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
                skip_upload=next_item.skip_upload,
            )
            next_item.job_id = job.job_id
            _save_pool_to_disk()

            from .pipeline import _run_pipeline_from
            await _run_pipeline_from(job, 0)

            next_item.status = "finished"
            next_item.finished_at = time.time()
            next_item.video_url = job.video_url or ""
            next_item.studio_url = job.studio_url or ""
            _update_meta_status(next_item.source, "finished")
        except Exception:
            next_item.status = "error"
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
            break
    _pool_state["current"] = None


def redo_current():
    cur = _pool_state.get("current")
    if not cur:
        return
    for it in _pool:
        if it.source == cur:
            it.status = "queued"
            _update_meta_status(cur, "queued")
            break


def clear_finished():
    global _pool
    _pool = [it for it in _pool if it.status != "finished"]
    _save_pool_to_disk()