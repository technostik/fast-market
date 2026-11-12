"""Transcript reuse: long_publish must not re-run Whisper when a transcript
already exists for the source (sidecar, meta log, or ASS from a prior run).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import webux.long_publish.pipeline as pipe
import webux.long_publish.register as reg
from webux.long_publish.models import Job, Step, STEP_NAMES

ASS_BODY = (
    "[Events]\n"
    "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,hello world\n"
)


def _job(tmp_path: Path) -> Job:
    return Job(
        job_id="test",
        source=str(tmp_path / "clip.mp4"),
        prompt_title="t",
        prompt_summary="s",
        do_remove_silence=False,
        do_normalize_volume=False,
        do_add_signature=False,
        do_generate_thumbnail=False,
        skip_upload=True,
        language="fr",
        model="medium",
        privacy="unlisted",
        use_modal=False,
        steps=[Step(name=n) for n in STEP_NAMES],
    )


def _patch_pipeline(monkeypatch, tmp_path: Path, recorded: list) -> None:
    async def fake_run(job, step, *cmd):
        recorded.append(list(cmd))
        if "extract-transcript" in cmd and "ass" in cmd:
            out = Path(cmd[cmd.index("-o") + 1])
            out.write_text(ASS_BODY, encoding="utf-8")
        if "apply" in cmd:
            return 0, "Generated title"
        return 0, ""

    monkeypatch.setattr(pipe, "_run", fake_run)
    # Step 2's summary call spawns the prompt binary directly, so it still
    # raises after steps 0-1 have run — enough to inspect the transcript step.
    monkeypatch.setattr(pipe, "_pr", lambda: "/nonexistent/prompt-bin")
    monkeypatch.setattr(
        pipe, "_load_publish_cfg",
        lambda profile=None: {"video_source_path": str(tmp_path)},
    )


def _run_until_step2(job: Job) -> None:
    with pytest.raises(FileNotFoundError):
        asyncio.run(pipe._run_pipeline_core(job, 0))


def test_reuses_sidecar_transcript(tmp_path: Path, monkeypatch):
    (tmp_path / "clip.mp4").write_bytes(b"x")
    sidecar = tmp_path / "clip_transcript.txt"
    sidecar.write_text("bonjour le monde", encoding="utf-8")
    recorded: list = []
    _patch_pipeline(monkeypatch, tmp_path, recorded)
    job = _job(tmp_path)

    _run_until_step2(job)

    assert not any("extract-transcript" in cmd for cmd in recorded)
    assert job.files["transcript_txt"] == str(sidecar)
    assert job.transcript_text == "bonjour le monde"
    assert job.steps[1].status == "done"
    assert "♻ Reused existing transcript" in job.steps[1].output
    meta = json.loads((tmp_path / "clip-long-meta.json").read_text())
    assert meta["files"]["transcript_txt"] == str(sidecar)


def test_reuses_ass_recorded_in_meta(tmp_path: Path, monkeypatch):
    (tmp_path / "clip.mp4").write_bytes(b"x")
    ass = tmp_path / "clip.ass"
    ass.write_text(ASS_BODY, encoding="utf-8")
    (tmp_path / "clip-long-meta.json").write_text(
        json.dumps({"files": {"transcript": str(ass)}}), encoding="utf-8"
    )
    recorded: list = []
    _patch_pipeline(monkeypatch, tmp_path, recorded)
    job = _job(tmp_path)

    _run_until_step2(job)

    assert not any("extract-transcript" in cmd for cmd in recorded)
    assert job.transcript_text == "hello world"
    assert Path(job.files["transcript_txt"]).exists()


def test_transcribes_when_no_transcript_exists(tmp_path: Path, monkeypatch):
    (tmp_path / "clip.mp4").write_bytes(b"x")
    recorded: list = []
    _patch_pipeline(monkeypatch, tmp_path, recorded)
    job = _job(tmp_path)

    _run_until_step2(job)

    transcribe = [cmd for cmd in recorded if "extract-transcript" in cmd]
    assert len(transcribe) == 1
    assert "--format" in transcribe[0] and "ass" in transcribe[0]
    assert job.transcript_text == "hello world"
    assert "Done in" in job.steps[1].output


def test_placeholders_are_not_reused(tmp_path: Path, monkeypatch):
    (tmp_path / "clip.mp4").write_bytes(b"x")
    (tmp_path / "clip_transcript.txt").write_text(
        "(transcript unavailable)", encoding="utf-8"
    )
    recorded: list = []
    _patch_pipeline(monkeypatch, tmp_path, recorded)
    job = _job(tmp_path)

    _run_until_step2(job)

    assert any("extract-transcript" in cmd for cmd in recorded)


def test_review_info_finds_sidecar_before_any_run(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    (tmp_path / "clip_transcript.txt").write_text("quick prompt text", encoding="utf-8")
    app = FastAPI()
    app.include_router(reg.router)
    with TestClient(app) as client:
        body = client.post("/review-info", json={"source": str(src)}).json()
    assert body["transcript_text"] == "quick prompt text"


def test_resume_reuses_ass_transcript_without_sidecar(tmp_path: Path, monkeypatch):
    """Resume from step 3 must accept a transcript that only exists as ASS."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    ass = tmp_path / "clip.ass"
    ass.write_text(ASS_BODY, encoding="utf-8")
    (tmp_path / "clip-long-meta.json").write_text(
        json.dumps({
            "completed_steps": [0, 1, 2],
            "skipped_steps": [],
            "title": "T",
            "description": "D",
            "files": {"transcript": str(ass)},
        }),
        encoding="utf-8",
    )
    captured: dict = {}

    def fake_from(job, from_step):
        captured["files"] = dict(job.files)

        async def _inner():
            return None

        return _inner()

    def fake_safe(coro, job):
        coro.close()

        async def _done():
            return None

        return _done()

    monkeypatch.setattr(reg, "_run_pipeline_from", fake_from)
    monkeypatch.setattr(reg, "_run_job_safely", fake_safe)

    app = FastAPI()
    app.include_router(reg.router)
    with TestClient(app) as client:
        response = client.post("/resume", json={
            "source": str(src), "prompt_title": "t", "prompt_summary": "s",
            "from_step": 3,
        })

    assert response.status_code == 200, response.text
    txt = Path(captured["files"]["transcript_txt"])
    assert txt == tmp_path / "clip_transcript.txt"
    assert txt.read_text(encoding="utf-8") == "hello world"
