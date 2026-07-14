from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

from fastapi import HTTPException

from common.core.config import load_tool_config, save_tool_config


def _load_publish_cfg() -> dict:
    try:
        cfg = load_tool_config("youtube")
        return cfg.get("youtube", {}).get("publish", {})
    except Exception:
        return {}


def _save_publish_cfg(pub: dict) -> None:
    try:
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
    meta: dict = {
        "source": job.source,
        "completed_steps": [i for i, s in enumerate(job.steps) if s.status == "done"],
        "skipped_steps": [i for i, s in enumerate(job.steps) if s.status == "skipped"],
        "files": job.files,
    }
    if job.title:
        meta["title"] = job.title
    if job.description:
        meta["description"] = job.description
    if job.source_urls:
        meta["source_urls"] = job.source_urls
    if job.description_prefix:
        meta["description_prefix"] = job.description_prefix
    if job.transcript_text:
        meta["transcript_text"] = job.transcript_text
    if job.video_url:
        meta["video_url"] = job.video_url
    if job.studio_url:
        meta["studio_url"] = job.studio_url
    if job.check_result is not None:
        meta["check_result"] = job.check_result
    try:
        with open(_meta_path(job.source), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


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


def _extract_video_id(url: str) -> str:
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else ""


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


async def _run(step, *cmd: str):
    from .state import set_active_proc, clear_active_proc

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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
