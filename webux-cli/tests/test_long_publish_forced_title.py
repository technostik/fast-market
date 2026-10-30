"""Manual mode for long publish: a forced title removes every AI input.

A non-empty title_override must skip the Whisper pass (step 1), both LLM
calls (step 2) and the thumbnail step (step 3). A description_override only
replaces the LLM summary.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import webux.long_publish.register as reg
import webux.long_publish.pipeline as pipe
from webux.long_publish.models import Job, Step, STEP_NAMES
from webux.long_publish.utils import _save_meta


PROMPT_BIN = "/fake/prompt-bin"


@pytest.fixture
def client():
    return client_app()


def _src(tmp_path: Path) -> Path:
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"x")
    return src


def _run_core(tmp_path: Path, monkeypatch, recorded: list, pub: dict | None = None, **job_kwargs) -> Job:
    def fake_run(step, *cmd):
        async def _inner():
            recorded.append(list(cmd))
            if cmd and cmd[0] == PROMPT_BIN:
                if step is not None:
                    step.output = (step.output + "\n" if step.output else "") + "IA"
                return 0, ""
            if "-o" in cmd:
                out = Path(cmd[cmd.index("-o") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"x")
            return 0, ""
        return _inner()

    monkeypatch.setattr(pipe, "_run", fake_run)
    monkeypatch.setattr(pipe, "_run_capture", fake_run)
    monkeypatch.setattr(pipe, "_pr", lambda: PROMPT_BIN)
    monkeypatch.setattr(
        pipe,
        "_load_publish_cfg",
        lambda profile=None: pub if pub is not None else {"video_source_path": str(tmp_path)},
    )
    defaults = dict(
        job_id="test",
        source=str(_src(tmp_path)),
        prompt_title="t",
        prompt_summary="s",
        do_remove_silence=True,
        language="fr",
        model="medium",
        privacy="unlisted",
        use_modal=False,
        do_normalize_volume=False,
        do_add_signature=False,
        do_generate_thumbnail=False,
        skip_upload=True,
    )
    defaults.update(job_kwargs)
    return Job(steps=[Step(name=n) for n in STEP_NAMES], **defaults)


def _prompt_calls(recorded: list) -> list:
    return [c for c in recorded if c and c[0] == PROMPT_BIN]


def _transcript_calls(recorded: list) -> list:
    return [c for c in recorded if "extract-transcript" in c]


def test_forced_title_skips_whisper_llm_and_thumbnail(tmp_path: Path, monkeypatch):
    recorded: list = []
    job = _run_core(
        tmp_path,
        monkeypatch,
        recorded,
        pub={"video_source_path": str(tmp_path), "signature": "— Sig"},
        title_override="Mon Titre Manuel",
        description_override="Ma description.",
        description_prefix="Préfixe",
        source_urls=["https://a.example"],
        do_generate_thumbnail=True,
    )

    asyncio.run(pipe._run_pipeline_core(job, 0))

    assert _transcript_calls(recorded) == []
    assert _prompt_calls(recorded) == []

    assert job.steps[1].status == "skipped"
    assert "manual title" in job.steps[1].output
    assert "Whisper" in job.steps[1].output

    assert job.title == "Mon Titre Manuel"
    assert job.description == "Préfixe\n\nSources:\n- https://a.example\n\nMa description.\n\n— Sig"
    assert job.steps[2].output.startswith("✍ Manual title")
    assert job.steps[2].status == "done"

    assert job.steps[3].status == "skipped"
    assert "manual title" in job.steps[3].output
    assert Path(job.files["final_video"]).name == "Mon Titre Manuel.mp4"


def test_forced_title_without_description_uses_prefix_only(tmp_path: Path, monkeypatch):
    recorded: list = []
    job = _run_core(
        tmp_path,
        monkeypatch,
        recorded,
        title_override="Titre",
        description_prefix="Préfixe",
    )

    asyncio.run(pipe._run_pipeline_core(job, 0))

    assert _prompt_calls(recorded) == []
    assert job.description == "Préfixe"


def test_description_override_only_keeps_title_llm(tmp_path: Path, monkeypatch):
    recorded: list = []
    job = _run_core(
        tmp_path,
        monkeypatch,
        recorded,
        description_override="Description manuelle",
        do_generate_thumbnail=False,
    )

    asyncio.run(pipe._run_pipeline_core(job, 0))

    # Whisper and the title LLM still run; only the summary is replaced.
    assert len(_transcript_calls(recorded)) == 1
    assert len(_prompt_calls(recorded)) == 1
    assert job.steps[1].status == "done"
    assert job.steps[2].status == "done"
    assert job.title == "IA"
    assert job.description == "Description manuelle"


def test_normal_run_still_calls_whisper_and_both_prompts(tmp_path: Path, monkeypatch):
    recorded: list = []
    job = _run_core(tmp_path, monkeypatch, recorded)

    with pytest.raises(FileNotFoundError):
        asyncio.run(pipe._run_pipeline_core(job, 0))

    assert len(_transcript_calls(recorded)) == 1
    assert len(_prompt_calls(recorded)) == 1


def test_meta_roundtrip_keeps_overrides(tmp_path: Path):
    src = _src(tmp_path)
    job = Job(
        job_id="j", source=str(src), prompt_title="t", prompt_summary="s",
        do_remove_silence=True, language="fr", model="medium", privacy="unlisted",
        title_override="Titre", description_override="Desc",
        steps=[Step(name=n) for n in STEP_NAMES],
    )

    _save_meta(job)
    meta = json.loads((tmp_path / "clip-long-meta.json").read_text(encoding="utf-8"))

    assert meta["title_override"] == "Titre"
    assert meta["description_override"] == "Desc"


def test_resume_restores_manual_title_from_meta(tmp_path: Path, monkeypatch):
    src = _src(tmp_path)
    final = tmp_path / "Titre.mp4"
    final.write_bytes(b"x")
    meta = {
        "source": str(src),
        "completed_steps": [0, 1, 2],
        "skipped_steps": [],
        "title": "Titre",
        "description": "Desc",
        "title_override": "Titre",
        "description_override": "Desc",
        "files": {"final_video": str(final)},
    }
    (tmp_path / "clip-long-meta.json").write_text(json.dumps(meta), encoding="utf-8")

    captured = {}

    def fake_from(job, from_step):
        captured["job"] = job

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
    monkeypatch.setattr(reg, "_load_publish_cfg", lambda profile=None: {})

    with client_app() as c:
        r = c.post("/resume", json={
            "source": str(src), "prompt_title": "t", "prompt_summary": "s",
            "from_step": 3,
        })
    assert r.status_code == 200, r.text
    job = captured["job"]
    assert job.title_override == "Titre"
    assert job.description_override == "Desc"
    assert job.title == "Titre"


def test_resume_with_cleared_title_returns_to_ai_mode(tmp_path: Path, monkeypatch):
    src = _src(tmp_path)
    final = tmp_path / "Titre.mp4"
    final.write_bytes(b"x")
    meta = {
        "source": str(src),
        "completed_steps": [0, 1, 2],
        "skipped_steps": [],
        "title": "Titre",
        "description": "Desc",
        "title_override": "Titre",
        "description_override": "Desc",
        "files": {"final_video": str(final)},
    }
    (tmp_path / "clip-long-meta.json").write_text(json.dumps(meta), encoding="utf-8")
    captured: dict = {}

    def fake_from(job, from_step):
        captured["job"] = job

        async def _inner():
            return None
        return _inner()

    monkeypatch.setattr(reg, "_run_pipeline_from", fake_from)
    monkeypatch.setattr(reg, "_run_job_safely", _noop_safe)
    monkeypatch.setattr(reg, "_load_publish_cfg", lambda profile=None: {})

    with client_app() as c:
        r = c.post("/resume", json={
            "source": str(src), "prompt_title": "t", "prompt_summary": "s",
            "from_step": 3, "title_override": "", "description_override": "",
        })
    # Back to AI mode past step 1 needs the transcript this run never made.
    assert r.status_code == 400
    assert "Transcript text not found" in r.json()["detail"]

    with client_app() as c:
        r = c.post("/resume", json={
            "source": str(src), "prompt_title": "t", "prompt_summary": "s",
            "from_step": 1, "title_override": "", "description_override": "",
        })
    assert r.status_code == 200, r.text
    assert captured["job"].title_override == ""
    assert captured["job"].description_override == ""


def test_start_rejects_too_long_manual_title(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(reg, "_load_publish_cfg", lambda profile=None: {})
    monkeypatch.setattr(reg, "_run_pipeline_from", _noop_coro_factory())
    monkeypatch.setattr(reg, "_run_job_safely", _noop_safe)
    with client_app() as c:        r = c.post("/start", json={
            "source": str(_src(tmp_path)),
            "prompt_title": "t",
            "prompt_summary": "s",
            "title_override": "x" * 101,
        })
    assert r.status_code == 400
    assert "YouTube allows 100" in r.json()["detail"]


def test_start_rejects_manual_title_with_rhythm(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(reg, "_load_publish_cfg", lambda profile=None: {})
    monkeypatch.setattr(reg, "_run_pipeline_from", _noop_coro_factory())
    monkeypatch.setattr(reg, "_run_job_safely", _noop_safe)
    with client_app() as c:
        r = c.post("/start", json={
            "source": str(_src(tmp_path)),
            "prompt_title": "t",
            "prompt_summary": "s",
            "rhythm_silence": True,
            "use_modal": False,
            "title_override": "Titre",
        })
    assert r.status_code == 400
    assert "rhythm" in r.json()["detail"].lower()


def client_app():
    app = FastAPI()
    app.include_router(reg.router)
    return TestClient(app)


def _noop_coro_factory():
    def fake_from(job, from_step):
        async def _inner():
            return None
        return _inner()
    return fake_from


def _noop_safe(coro, job):
    coro.close()

    async def _done():
        return None
    return _done()
