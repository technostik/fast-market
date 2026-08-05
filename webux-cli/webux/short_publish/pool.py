from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import DEFAULT_VIDEO_SOURCE_PATH, STEP_NAMES
from .utils import _load_publish_cfg, _load_meta


@dataclass
class PoolItem:
    source: str
    title_override: str = ""
    description_prefix: str = ""
    source_urls: list[str] = field(default_factory=list)
    skip_upload: bool = False
    transcript_mode: str = "normal"
    do_normalize_volume: bool = False
    do_charisma: bool = True
    do_add_signature: bool = True
    do_ignore_post_publish: bool = False
    status: str = "queued"  # queued | processing | finished | skipped | error
    added_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    job_id: Optional[str] = None  # set when processing starts
    video_url: str = ""
    studio_url: str = ""
    elapsed_seconds: Optional[float] = None
    error_message: str = ""
    title: str = ""
    check_result: Optional[str] = None
    charisma_score: str = ""
    charisma_notes: str = ""
    retry_from_step: Optional[int] = None
    retry_count: int = 0


_pool: list[PoolItem] = []
_pool_state = {"running": False, "current": None}
# When False, get_pool_state() must NOT auto-restart the worker (e.g. after an
# explicit Stop). Set back to True by start_pool()/add_to_pool().
_pool_auto_start = True
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
                title_override=item.get("title_override", ""),
                description_prefix=item.get("description_prefix", ""),
                source_urls=item.get("source_urls", []),
                skip_upload=item.get("skip_upload", False),
                transcript_mode=item.get("transcript_mode") or ("groq" if item.get("use_groq") else "normal"),
                do_normalize_volume=item.get("do_normalize_volume", False),
                do_charisma=item.get("do_charisma", True),
                do_add_signature=item.get("do_add_signature", True),
                do_ignore_post_publish=item.get("do_ignore_post_publish", False),
                # processing items were interrupted by server restart — reset them
                status="queued" if item.get("status") == "processing" else item.get("status", "queued"),
                added_at=item.get("added_at", time.time()),
                finished_at=item.get("finished_at"),
                video_url=item.get("video_url", ""),
                studio_url=item.get("studio_url", ""),
                title=item.get("title", "") or _load_meta(item["source"]).get("title", ""),
                check_result=item.get("check_result"),
                charisma_score=item.get("charisma_score", ""),
                charisma_notes=item.get("charisma_notes", ""),
                retry_count=item.get("retry_count", 0),
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
                "title_override": it.title_override,
                "description_prefix": it.description_prefix,
                "source_urls": it.source_urls,
                "skip_upload": it.skip_upload,
                "transcript_mode": it.transcript_mode,
                "do_normalize_volume": it.do_normalize_volume,
                "do_charisma": it.do_charisma,
                "do_add_signature": it.do_add_signature,
                "do_ignore_post_publish": it.do_ignore_post_publish,
                "status": it.status,
                "added_at": it.added_at,
                "finished_at": it.finished_at,
                "video_url": it.video_url,
                "studio_url": it.studio_url,
                "title": it.title,
                "check_result": it.check_result,
                "charisma_score": it.charisma_score,
                "charisma_notes": it.charisma_notes,
                "retry_count": it.retry_count,
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


def add_to_pool(source: str, description_prefix: str = "", source_urls: list[str] | None = None, skip_upload: bool = False, transcript_mode: str = "normal", do_normalize_volume: bool = False, do_charisma: bool = True, do_add_signature: bool = True, do_ignore_post_publish: bool = False, title_override: str = "") -> bool:
    src = str(Path(source).expanduser().resolve())
    if any(item.source == src for item in _pool):
        return False
    source_urls = source_urls or []
    item = PoolItem(source=src, title_override=title_override, description_prefix=description_prefix, source_urls=source_urls, skip_upload=skip_upload, transcript_mode=transcript_mode, do_normalize_volume=do_normalize_volume, do_charisma=do_charisma, do_add_signature=do_add_signature, do_ignore_post_publish=do_ignore_post_publish)
    _pool.append(item)
    _create_meta(src, description_prefix, source_urls)
    _save_pool_to_disk()
    start_pool()  # begin processing immediately (preserves add → run UX)
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
            it.retry_count = 0
            _update_meta_status(src, "queued")
            _save_pool_to_disk()
            start_pool()
            return True
    return False


def retry_item(source: str) -> bool:
    """Requeue an error/stopped pool item, resuming from the first failed step.
    Each subsequent retry goes back one more step (progressive rollback)."""
    src = str(Path(source).expanduser().resolve())
    for it in _pool:
        if it.source == src and it.status in ("error", "stopped"):
            meta = _load_meta(src)
            completed = set(meta.get("completed_steps", []))
            skipped = set(meta.get("skipped_steps", []))
            passed = completed | skipped
            # First step not yet completed or skipped is the retry entry point
            base_from_step = 0
            for i in range(len(STEP_NAMES)):
                if i not in passed:
                    base_from_step = i
                    break
            else:
                # All steps passed — shouldn't happen for error/stopped, but fallback to 0
                base_from_step = 0
            it.retry_count += 1
            from_step = max(0, base_from_step - it.retry_count)
            it.status = "queued"
            it.finished_at = None
            it.elapsed_seconds = None
            it.error_message = ""
            it.job_id = None
            it.retry_from_step = from_step
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
    # Auto-start the pool worker only if it is not explicitly stopped and
    # there is work to do. After an explicit Stop, _pool_auto_start is False so
    # status polls never silently restart the pool.
    if not _pool_state["running"] and _pool_auto_start:
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
            "title_override": it.title_override,
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
            "title": it.title,
            "check_result": it.check_result,
            "charisma_score": it.charisma_score,
            "charisma_notes": it.charisma_notes,
            "retry_count": it.retry_count,
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

        # ── Source file missing guard ───────────────────────────────────────────
        if not Path(next_item.source).expanduser().exists():
            next_item.status = "error"
            next_item.finished_at = time.time()
            next_item.error_message = (
                f"[source] Source file not found: {next_item.source}\n"
                "Remove this item from the pool manually (pool/remove) and re-add an existing file."
            )
            _update_meta_status(next_item.source, "error")
            _save_pool_to_disk()
            _pool_state["current"] = None
            next_item.job_id = None
            continue

        # Create Job and store job_id so UI can show progress
        try:
            from .register import _create_publish_job  # circular-safe

            job = _create_publish_job(
                source=next_item.source,
                description_prefix=next_item.description_prefix,
                source_urls=next_item.source_urls,
                skip_upload=next_item.skip_upload,
                transcript_mode=next_item.transcript_mode,
                do_normalize_volume=next_item.do_normalize_volume,
                do_charisma=next_item.do_charisma,
                do_add_signature=next_item.do_add_signature,
                do_ignore_post_publish=next_item.do_ignore_post_publish,
                title_override=next_item.title_override,
            )
            next_item.job_id = job.job_id
            _save_pool_to_disk()

            from .pipeline import _run_pipeline_from, _run_job_safely
            from_step = next_item.retry_from_step if next_item.retry_from_step is not None else 0
            next_item.retry_from_step = None
            await _run_job_safely(_run_pipeline_from(job, from_step), job)

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
            elif job.status == "stopped":
                next_item.status = "stopped"
                next_item.finished_at = time.time()
                if job.start_time:
                    next_item.elapsed_seconds = round(time.time() - job.start_time, 1)
                next_item.error_message = "Stopped by user"
                _update_meta_status(next_item.source, "stopped")
            else:
                next_item.status = "finished"
                next_item.finished_at = time.time()
                next_item.retry_count = 0
                next_item.video_url = job.video_url or ""
                next_item.studio_url = job.studio_url or ""
                next_item.title = job.title or ""
                next_item.check_result = job.check_result
                next_item.charisma_score = job.files.get("charisma_score", "")
                next_item.charisma_notes = job.files.get("charisma_notes", "")
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
    global _worker_task, _pool_state, _pool_auto_start
    if _pool_state["running"]:
        return
    _pool_state["running"] = True
    _pool_auto_start = True
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_pool_worker())


def stop_pool():
    global _pool_state, _pool_auto_start
    _pool_state["running"] = False
    _pool_auto_start = False


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


_UNFINISHED = {"queued", "processing", "error", "stopped", "skipped"}


def redo_unfinished():
    """Requeue every unfinished pool item and start processing them all."""
    requeued = False
    for it in _pool:
        if it.status in _UNFINISHED:
            it.status = "queued"
            it.finished_at = None
            it.elapsed_seconds = None
            it.error_message = ""
            it.job_id = None
            it.retry_count = 0
            _update_meta_status(it.source, "queued")
            requeued = True
    _save_pool_to_disk()
    if requeued:
        start_pool()


def clear_finished():
    global _pool
    _pool = [it for it in _pool if it.status != "finished"]
    _save_pool_to_disk()


async def rerun_check(source: str) -> str | None:
    from .utils import _pr, _stem
    src = str(Path(source).expanduser().resolve())
    item = next((it for it in _pool if it.source == src), None)
    if not item:
        return None
    pub = _load_publish_cfg()
    check_prompt = pub.get("default_check_prompt", "").strip()
    if not check_prompt:
        return None
    d = Path(pub.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH)).expanduser().resolve()
    txt_path = d / f"{_stem(src)}_transcript.txt"
    if not txt_path.exists():
        return None
    proc = await asyncio.create_subprocess_exec(
        _pr(), "apply", check_prompt, f"transcript=@{txt_path}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    result = stdout.decode(errors="replace").strip() if proc.returncode == 0 else None
    if result is not None:
        item.check_result = result
        _save_pool_to_disk()
    return result


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