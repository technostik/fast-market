"""Add a just-published YouTube video to the corpus.

Called by the long and short publish pipelines right after a successful
upload, when the URL, title, description and transcript are all known. The
content is indexed directly through ``corpus add`` — no YouTube API call, no
quota, and it works for an unlisted/private video whose captions are not
processed yet.

Indexing is best effort: a failure is appended as a warning to the upload step
and never fails the publish.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from common import structlog

logger = structlog.get_logger(__name__)

# Transcripts written by the pipelines when none was produced. Indexing them
# would poison the corpus with a fake sentence.
_PLACEHOLDER_PREFIXES = ("(transcript unavailable)", "(no transcript")

CORPUS_ADD_TIMEOUT = 900.0


@dataclass
class CorpusResult:
    ok: bool
    handle: str = ""
    error: str = ""
    already: bool = False


def _corpus() -> str:
    return shutil.which("corpus") or "corpus"


def transcript_text(job) -> str:
    """Transcript to index: the transcript file when present, else the job text."""
    path = str((getattr(job, "files", {}) or {}).get("transcript_txt", "") or "")
    text = ""
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            text = ""
    if not text.strip():
        text = str(getattr(job, "transcript_text", "") or "")
    text = text.strip()
    if not text or text.lower().startswith(_PLACEHOLDER_PREFIXES):
        return ""
    return text


async def _run_corpus_add(
    job, video_id: str, *, env: dict, duration: float | None
) -> CorpusResult:
    transcript = transcript_text(job)
    if not transcript:
        return CorpusResult(
            ok=False, error="no transcript available — not added to the corpus"
        )
    title = str(getattr(job, "title", "") or "").strip()
    if not title:
        return CorpusResult(
            ok=False, error="no title available — not added to the corpus"
        )
    url = str(getattr(job, "video_url", "") or "") or (
        f"https://www.youtube.com/watch?v={video_id}"
    )
    description = str(getattr(job, "description", "") or "").strip()

    with tempfile.TemporaryDirectory(prefix="corpus-add-") as tmp:
        transcript_file = Path(tmp) / "transcript.txt"
        description_file = Path(tmp) / "description.txt"
        transcript_file.write_text(transcript, encoding="utf-8")
        description_file.write_text(description, encoding="utf-8")
        cmd = [
            _corpus(), "add",
            "--source", "youtube",
            "--id", video_id,
            "--url", url,
            "--title", title,
            "--transcript-file", str(transcript_file),
            "--description-file", str(description_file),
            "--privacy", str(getattr(job, "privacy", "") or "unknown"),
            "--format", "json",
        ]
        if duration and duration > 0:
            cmd += ["--duration", str(int(round(duration)))]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            return CorpusResult(ok=False, error=f"cannot run corpus CLI: {exc}")

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=CORPUS_ADD_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return CorpusResult(
                ok=False,
                error=f"corpus add timed out after {CORPUS_ADD_TIMEOUT:.0f}s",
            )

    raw_out = (stdout or b"").decode(errors="replace").strip()
    raw_err = (stderr or b"").decode(errors="replace").strip()
    if proc.returncode != 0:
        detail = raw_err or raw_out or f"exit {proc.returncode}"
        return CorpusResult(ok=False, error=detail[-500:])

    handle = ""
    start = raw_out.find("{")
    end = raw_out.rfind("}")
    if start != -1 and end > start:
        try:
            payload = json.loads(raw_out[start : end + 1])
            handle = str(payload.get("handle", "") or "")
        except (json.JSONDecodeError, TypeError, AttributeError):
            handle = ""
    return CorpusResult(ok=True, handle=handle)


async def maybe_add_to_corpus(
    job,
    video_id: str,
    step,
    *,
    env: dict,
    duration: float | None = None,
    save_meta: Callable[[], None] | None = None,
) -> CorpusResult:
    """Index the uploaded video when the job asked for it (never raises).

    Idempotent: once ``job.corpus_video_id`` matches the upload, a resume or
    retry does not index the same video twice.
    """
    if not getattr(job, "do_add_to_corpus", True):
        return CorpusResult(ok=False)
    if getattr(job, "skip_upload", False) or not video_id:
        return CorpusResult(ok=False)
    if getattr(job, "stop_requested", False):
        return CorpusResult(ok=False)
    if getattr(job, "corpus_video_id", "") == video_id:
        return CorpusResult(
            ok=True, handle=getattr(job, "corpus_handle", ""), already=True
        )

    logger.info(
        "corpus_add_started",
        video_id=video_id,
        profile=getattr(job, "profile", "") or "",
    )
    try:
        result = await _run_corpus_add(job, video_id, env=env, duration=duration)
    except Exception as exc:  # never fail the publish for a corpus add
        logger.error("corpus_add_failed", video_id=video_id, error=str(exc))
        result = CorpusResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    if result.ok:
        job.corpus_video_id = video_id
        job.corpus_handle = result.handle
        if result.handle:
            step.output += f"\n➕ Added to corpus: {result.handle}"
        logger.info("corpus_add_done", video_id=video_id, handle=result.handle)
    else:
        step.output += f"\n⚠ Corpus add failed (non-blocking): {result.error}"
        logger.warning(
            "corpus_add_warning", video_id=video_id, error=result.error
        )

    if save_meta:
        save_meta()
    return result
