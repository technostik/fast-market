from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import HTTPException

from common.core.config import load_tool_config, save_tool_config


def _profile_context(profile: str | None):
    @contextlib.contextmanager
    def _ctx():
        old = os.environ.get("FASTMARKET_PROFILE")
        if profile:
            os.environ["FASTMARKET_PROFILE"] = profile
        try:
            yield
        finally:
            if old is None:
                os.environ.pop("FASTMARKET_PROFILE", None)
            else:
                os.environ["FASTMARKET_PROFILE"] = old
    return _ctx()


def _load_publish_cfg(profile: str | None = None) -> dict:
    try:
        with _profile_context(profile):
            cfg = load_tool_config("youtube")
        return cfg.get("youtube", {}).get("publish", {})
    except Exception:
        return {}


def _save_publish_cfg(pub: dict, profile: str | None = None) -> None:
    try:
        with _profile_context(profile):
            cfg = load_tool_config("youtube")
            yt = cfg.setdefault("youtube", {})
            yt["publish"] = pub
            save_tool_config("youtube", cfg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {exc}")


def _meta_path(source: str) -> Path:
    p = Path(source)
    return p.parent / f"{p.stem}-meta.json"


def _save_meta(job) -> None:
    existing = _load_meta(job.source)
    meta: dict = {
        "source": job.source,
        "completed_steps": [i for i, s in enumerate(job.steps) if s.status == "done"],
        "skipped_steps": [i for i, s in enumerate(job.steps) if s.status == "skipped"],
        "files": job.files,
    }

    def _set(key: str, value) -> None:
        """Write the job value, else keep what the meta already knows.

        Jobs created outside the run form (redo post-publish, resume, re-upload)
        do not carry every processed-video fact; rebuilding the meta from scratch
        used to erase them.
        """
        if value:
            meta[key] = value
        elif existing.get(key):
            meta[key] = existing[key]

    _set("title", job.title)
    _set("description", job.description)
    _set("description_raw", getattr(job, "description_raw", ""))
    _set("transcript_text", job.transcript_text)
    _set("description_prefix", job.description_prefix)
    if job.source_urls:
        meta["source_urls"] = job.source_urls
    if job.cut_time:
        # Never carried over: cut_time is a one-time operation.
        meta["cut_time"] = job.cut_time
    if getattr(job, "profile", ""):
        meta["profile"] = job.profile
    elif existing.get("profile"):
        meta["profile"] = existing["profile"]

    # The latest successful upload stays visible until the next one succeeds.
    video_url = str(job.video_url or existing.get("video_url", "") or "")
    if video_url:
        meta["video_url"] = video_url
    if job.studio_url:
        meta["studio_url"] = job.studio_url
    elif not job.video_url and existing.get("studio_url"):
        meta["studio_url"] = existing["studio_url"]

    # A pinned comment belongs to one specific video: keep the previous one only
    # while that video is still the latest upload (a re-upload must not inherit
    # the old channel's comment id and skip posting on the new channel).
    same_video = bool(video_url) and video_url == str(existing.get("video_url", "") or "")
    pinned_id = getattr(job, "pinned_comment_id", "") or (
        existing.get("pinned_comment_id", "") if same_video else ""
    )
    pinned_url = getattr(job, "pinned_comment_url", "") or (
        existing.get("pinned_comment_url", "") if same_video else ""
    )
    if pinned_id:
        meta["pinned_comment_id"] = pinned_id
    if pinned_url:
        meta["pinned_comment_url"] = pinned_url

    if job.check_result is not None:
        meta["check_result"] = job.check_result
    elif existing.get("check_result") is not None:
        meta["check_result"] = existing["check_result"]
    if getattr(job, "upload_duration_seconds", None) is not None:
        meta["upload_duration_seconds"] = job.upload_duration_seconds
    elif existing.get("upload_duration_seconds") is not None:
        meta["upload_duration_seconds"] = existing["upload_duration_seconds"]

    meta["uploads"] = _merge_upload_history(job, existing)
    try:
        with open(_meta_path(job.source), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _merge_upload_history(job, existing: dict) -> list[dict]:
    """Return the per-source upload history, keeping every channel the video
    was published to (a re-upload must never erase the previous upload).

    The current upload is appended once per distinct ``video_url``; a later save
    (e.g. after the pinned comment is posted) updates that same entry.
    """
    uploads = [dict(u) for u in (existing.get("uploads") or []) if isinstance(u, dict)]
    video_url = (job.video_url or "").strip()
    if not video_url:
        return uploads
    entry = next((u for u in uploads if (u.get("video_url") or "") == video_url), None)
    if entry is None:
        entry = {"video_url": video_url, "at": time.time()}
        uploads.append(entry)
    if getattr(job, "profile", ""):
        entry["profile"] = job.profile
    if job.studio_url:
        entry["studio_url"] = job.studio_url
    if getattr(job, "privacy", ""):
        entry["privacy"] = job.privacy
    if getattr(job, "pinned_comment_id", ""):
        entry["pinned_comment_id"] = job.pinned_comment_id
    if getattr(job, "pinned_comment_url", ""):
        entry["pinned_comment_url"] = job.pinned_comment_url
    return uploads


def _load_meta(source: str) -> dict:
    try:
        p = _meta_path(source)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _yt() -> str:
    return shutil.which("youtube") or "youtube"


def _pr() -> str:
    return shutil.which("prompt") or "prompt"


def _video() -> str:
    return shutil.which("video") or "video"


def _sound() -> str:
    return shutil.which("sound") or "sound"


def _stem(p: str) -> str:
    return Path(p).stem


def _dir(p: str) -> Path:
    return Path(p).resolve().parent


def _parse_timestamp(ts: str) -> float | None:
    """Parse a cut point into seconds. Accepts ``MM:SS``, ``HH:MM:SS`` or a bare
    number of seconds. Returns ``None`` for an empty/unparseable value."""
    ts = (ts or "").strip()
    if not ts:
        return None
    if ":" in ts:
        parts: list[float] = []
        for p in ts.split(":"):
            try:
                parts.append(float(p))
            except ValueError:
                return None
        if not parts:
            return None
        parts.reverse()
        seconds = 0.0
        for i, v in enumerate(parts):
            seconds += v * (60 ** i)
        return seconds
    try:
        return float(ts)
    except ValueError:
        return None


def _extract_video_id(url: str) -> str:
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else ""


def _job_env(job) -> dict:
    """Return environment dict for a job with correct FASTMARKET_PROFILE.

    Creates a copy of os.environ with FASTMARKET_PROFILE set to the job's profile,
    so subprocesses inherit the correct profile regardless of concurrent jobs.
    """
    import os
    env = os.environ.copy()
    if getattr(job, "profile", ""):
        env["FASTMARKET_PROFILE"] = job.profile
    return env


def _ass_to_plain_text(ass_path: str) -> str:
    import re
    lines = []
    with open(ass_path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("Dialogue:"):
                continue
            parts = line.split(",", 9)
            if len(parts) < 10:
                continue
            text = parts[9].strip()
            text = re.sub(r"\{[^}]*\}", "", text)
            if text:
                lines.append(text)
    return "\n".join(lines)


async def _get_video_duration(path: str) -> float:
    import subprocess
    result = await asyncio.to_thread(
        subprocess.run,
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format/duration",
            "-of", "default=noprint_wrappers:1:nokey=1",
            path,
        ],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


_duration_cache: dict[str, tuple[float, float]] = {}  # path -> (mtime, seconds)


def _get_video_duration_cli_sync(path: str) -> float:
    """Duration in seconds via the ``video duration`` CLI, cached by (path, mtime)."""
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return 0.0
    cached = _duration_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    result = subprocess.run(
        [_video(), "duration", path],
        capture_output=True, text=True,
    )
    try:
        seconds = float(result.stdout.strip())
    except ValueError:
        return 0.0
    _duration_cache[path] = (mtime, seconds)
    return seconds


async def _get_video_duration_cli(path: str) -> float:
    return await asyncio.to_thread(_get_video_duration_cli_sync, path)


SHORTS_MAX_SECONDS = 180.0


def _effective_limit_seconds(signature_duration: float = 0.0) -> float:
    """YouTube Shorts hard limit (180s) minus the signature video length that
    will be concatenated onto the clip later, so the resulting upload stays
    within the 3-minute limit."""
    return SHORTS_MAX_SECONDS - max(0.0, signature_duration)


def _sanitize_filename(title: str) -> str:
    import re
    safe = re.sub(r'[<>:"/\\|?*\n\r\t]', '', title)
    safe = safe.strip()
    safe = safe.strip('.-')
    return safe[:100] if safe else "video"


def _validate_urls(urls: list[str]) -> list[str]:
    result = []
    for u in urls:
        u = u.strip()
        if u and (u.startswith("http://") or u.startswith("https://")):
            result.append(u)
    return result


async def _run(job, step, *cmd: str):
    from .state import set_active_proc, clear_active_proc

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_job_env(job),
    )
    set_active_proc(proc)
    try:
        async def _stream(stream, prefix):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if text and step:
                    if step.output:
                        step.output += "\n"
                    step.output += f"{prefix}{text}"

        await asyncio.gather(
            _stream(proc.stdout, ""),
            _stream(proc.stderr, "[err] "),
            proc.wait(),
        )
    finally:
        clear_active_proc()
    rc = proc.returncode or 0
    # final out for caller compatibility (last non-empty line)
    out = ""
    if step and step.output:
        out = step.output.splitlines()[-1]
    return rc, out
