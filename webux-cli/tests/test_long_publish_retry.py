"""Retry continues a long publish from the first step missing in the meta log."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import webux.long_publish.register as reg


def _client():
    app = FastAPI()
    app.include_router(reg.router)
    return TestClient(app)


def _source(tmp_path: Path, completed: list[int], title: str = "Hello") -> Path:
    src = tmp_path / "clip.webm"
    src.write_bytes(b"x")
    transcript = tmp_path / "clip_transcript.txt"
    transcript.write_text("hello", encoding="utf-8")
    meta = {
        "source": str(src),
        "completed_steps": completed,
        "skipped_steps": [],
        "title": title,
        "description": "desc",
        "files": {"final_video": str(src), "transcript_txt": str(transcript)},
    }
    (tmp_path / "clip-long-meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return src


def test_check_resume_next_step_is_thumbnail(tmp_path: Path):
    src = _source(tmp_path, [0, 1, 2])
    with _client() as client:
        body = client.post("/check-resume", json={"source": str(src)}).json()
    assert body["meta_exists"] is True
    assert body["next_step"] == 3
    assert body["step_names"][3] == "Generate thumbnail"
    assert 3 in body["available_from_steps"]


def test_check_resume_without_meta(tmp_path: Path):
    src = tmp_path / "fresh.webm"
    src.write_bytes(b"x")
    with _client() as client:
        body = client.post("/check-resume", json={"source": str(src)}).json()
    assert body["meta_exists"] is False
    assert body["next_step"] is None
    assert body["can_resume"] is False


def test_check_resume_finished_log_has_no_next_step(tmp_path: Path):
    src = _source(tmp_path, [0, 1, 2, 3, 4, 5])
    with _client() as client:
        body = client.post("/check-resume", json={"source": str(src)}).json()
    assert body["meta_exists"] is True
    assert body["next_step"] is None


def test_resume_starts_at_thumbnail_with_local_engine(tmp_path: Path, monkeypatch):
    src = _source(tmp_path, [0, 1, 2])
    captured = {}

    def fake_from(job, from_step):
        captured["from_step"] = from_step
        captured["engine"] = job.thumbnail_engine

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

    with _client() as client:
        response = client.post("/resume", json={
            "source": str(src),
            "prompt_title": "t",
            "prompt_summary": "s",
            "from_step": 3,
            "thumbnail_engine": "flux2",
            "do_generate_thumbnail": True,
        })
    assert response.status_code == 200, response.text
    assert captured["from_step"] == 3
    assert captured["engine"] == "flux2"
    job = reg._jobs[response.json()["job_id"]]
    assert [s.status for s in job.steps[:3]] == ["done", "done", "done"]
    assert job.steps[3].status == "pending"
