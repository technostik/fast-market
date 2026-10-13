"""Rhythm (transcript-first) silence mode for long publish.

Backward compatibility: the flag defaults to False everywhere, so jobs
that do not opt in follow the exact old command sequence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import webux.long_publish.register as reg
import webux.long_publish.pipeline as pipe
from webux.long_publish.models import Job, Step, STEP_NAMES, RHYTHM_STEP_NAMES


def _client():
    app = FastAPI()
    app.include_router(reg.router)
    return TestClient(app)


def _no_real_pipeline(monkeypatch):
    """Neutralize job execution so API tests only exercise job creation."""

    def fake_from(job, from_step):
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


def _src(tmp_path: Path) -> Path:
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    return src


# ── API guards ──────────────────────────────────────────────────────────────

def test_start_rhythm_with_modal_rejected(tmp_path: Path, monkeypatch):
    _no_real_pipeline(monkeypatch)
    with _client() as client:
        response = client.post("/start", json={
            "source": str(_src(tmp_path)),
            "prompt_title": "t",
            "prompt_summary": "s",
            "use_modal": True,
            "rhythm_silence": True,
        })
    assert response.status_code == 400
    assert "local-only" in response.json()["detail"]


def test_start_rhythm_without_remove_silence_rejected(tmp_path: Path, monkeypatch):
    _no_real_pipeline(monkeypatch)
    with _client() as client:
        response = client.post("/start", json={
            "source": str(_src(tmp_path)),
            "prompt_title": "t",
            "prompt_summary": "s",
            "use_modal": False,
            "do_remove_silence": False,
            "rhythm_silence": True,
        })
    assert response.status_code == 400
    assert "Remove silence" in response.json()["detail"]


def test_start_rhythm_with_transcript_none_rejected(tmp_path: Path, monkeypatch):
    _no_real_pipeline(monkeypatch)
    monkeypatch.setattr(reg, "_load_publish_cfg", lambda: {"transcript_mode": "none"})
    with _client() as client:
        response = client.post("/start", json={
            "source": str(_src(tmp_path)),
            "prompt_title": "t",
            "prompt_summary": "s",
            "use_modal": False,
            "rhythm_silence": True,
        })
    assert response.status_code == 400
    assert "transcript" in response.json()["detail"].lower()


def test_start_rhythm_ok_sets_flag_and_step_names(tmp_path: Path, monkeypatch):
    _no_real_pipeline(monkeypatch)
    monkeypatch.setattr(reg, "_load_publish_cfg", lambda: _pub_with_rhythm())
    with _client() as client:
        response = client.post("/start", json={
            "source": str(_src(tmp_path)),
            "prompt_title": "t",
            "prompt_summary": "s",
            "use_modal": False,
            "rhythm_silence": True,
        })
    assert response.status_code == 200, response.text
    job = reg._jobs[response.json()["job_id"]]
    assert job.rhythm_silence is True
    assert [s.name for s in job.steps] == RHYTHM_STEP_NAMES


def test_start_default_is_backward_compatible(tmp_path: Path, monkeypatch):
    _no_real_pipeline(monkeypatch)
    monkeypatch.setattr(reg, "_load_publish_cfg", lambda: _pub_with_rhythm())
    with _client() as client:
        response = client.post("/start", json={
            "source": str(_src(tmp_path)),
            "prompt_title": "t",
            "prompt_summary": "s",
        })
    assert response.status_code == 200, response.text
    job = reg._jobs[response.json()["job_id"]]
    assert job.rhythm_silence is False
    assert [s.name for s in job.steps] == STEP_NAMES


def test_resume_rhythm_ok_and_modal_rejected(tmp_path: Path, monkeypatch):
    _no_real_pipeline(monkeypatch)
    body = {
        "source": str(_src(tmp_path)),
        "prompt_title": "t",
        "prompt_summary": "s",
        "from_step": 1,
        "use_modal": False,
        "do_remove_silence": True,
        "rhythm_silence": True,
    }
    with _client() as client:
        ok = client.post("/resume", json=body)
        assert ok.status_code == 200, ok.text
        job = reg._jobs[ok.json()["job_id"]]
        assert job.rhythm_silence is True

        bad = client.post("/resume", json={**body, "use_modal": True})
        assert bad.status_code == 400
        assert "local-only" in bad.json()["detail"]


# ── Rhythm tuning via publish config ────────────────────────────────────────

def _pub_with_rhythm(**over):
    pub = {
        "transcript_mode": "normal",
        "transcript_language": "fr",
        "transcript_model": "medium",
    }
    pub.update(over)
    return pub


def test_config_rhythm_roundtrip(monkeypatch):
    store = {}

    def _save(pub):
        store.clear()  # production replaces the publish section wholesale
        store.update(pub)

    monkeypatch.setattr(reg, "_load_publish_cfg", lambda: dict(store))
    monkeypatch.setattr(reg, "_save_publish_cfg", _save)
    monkeypatch.setattr(reg, "_migrate_publish_cfg_if_needed", lambda: False)
    with _client() as client:
        r = client.post("/config", json={
            "video_source_path": "/x",
            "rhythm_pause_sentence": 0.6,
            "rhythm_paragraph_threshold": 2.0,
        })
        assert r.status_code == 200, r.text
        cfg = client.get("/config").json()
    assert cfg["rhythm_pause_sentence"] == 0.6
    assert cfg["rhythm_paragraph_threshold"] == 2.0
    assert cfg["rhythm_pause_comma"] is None
    # Clearing fields sends explicit nulls (like the real frontend): the keys
    # are removed, so the video config default applies again.
    with _client() as client:
        r = client.post("/config", json={
            "video_source_path": "/x",
            "rhythm_pause_sentence": None,
            "rhythm_paragraph_threshold": None,
        })
        assert r.status_code == 200, r.text
    assert "rhythm_pause_sentence" not in store
    assert "rhythm_paragraph_threshold" not in store


def test_config_invalid_rhythm_rejected(monkeypatch):
    store = {}
    monkeypatch.setattr(reg, "_load_publish_cfg", lambda: dict(store))
    monkeypatch.setattr(reg, "_save_publish_cfg", lambda pub: store.update(pub))
    monkeypatch.setattr(reg, "_migrate_publish_cfg_if_needed", lambda: False)
    with _client() as client:
        r = client.post("/config", json={
            "video_source_path": "/x",
            "rhythm_pause_inline": -0.5,
        })
    assert r.status_code == 400
    assert "rhythm_pause_inline" in r.json()["detail"]


def test_start_uses_pub_rhythm_params_and_cut_time(tmp_path: Path, monkeypatch):
    _no_real_pipeline(monkeypatch)
    monkeypatch.setattr(
        reg, "_load_publish_cfg",
        lambda: _pub_with_rhythm(rhythm_pause_sentence=0.6, rhythm_crossfade=0.005),
    )
    with _client() as client:
        response = client.post("/start", json={
            "source": str(_src(tmp_path)),
            "prompt_title": "t",
            "prompt_summary": "s",
            "use_modal": False,
            "rhythm_silence": True,
            "cut_time": "1:30",
        })
    assert response.status_code == 200, response.text
    job = reg._jobs[response.json()["job_id"]]
    assert job.rhythm_params == {"rhythm_pause_sentence": 0.6, "rhythm_crossfade": 0.005}
    assert job.cut_time == "1:30"


def test_start_invalid_pub_rhythm_rejected(tmp_path: Path, monkeypatch):
    _no_real_pipeline(monkeypatch)
    monkeypatch.setattr(
        reg, "_load_publish_cfg",
        lambda: _pub_with_rhythm(rhythm_pause_inline="fast"),
    )
    with _client() as client:
        response = client.post("/start", json={
            "source": str(_src(tmp_path)),
            "prompt_title": "t",
            "prompt_summary": "s",
            "use_modal": False,
            "rhythm_silence": True,
        })
    assert response.status_code == 400
    assert "rhythm_pause_inline" in response.json()["detail"]


def test_start_cut_time_defaults_empty(tmp_path: Path, monkeypatch):
    _no_real_pipeline(monkeypatch)
    monkeypatch.setattr(reg, "_load_publish_cfg", lambda: _pub_with_rhythm())
    with _client() as client:
        response = client.post("/start", json={
            "source": str(_src(tmp_path)),
            "prompt_title": "t",
            "prompt_summary": "s",
        })
    assert response.status_code == 200, response.text
    job = reg._jobs[response.json()["job_id"]]
    assert job.cut_time == ""
    assert job.rhythm_params == {}


# ── Pipeline command order (mocked subprocesses) ────────────────────────────

def _fake_run_factory(recorded: list):
    async def fake_run(step, *cmd):
        recorded.append(list(cmd))
        if "-o" in cmd:
            out = Path(cmd[cmd.index("-o") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            if "ass" in cmd:
                out.write_text(
                    "[Events]\n"
                    "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,hello world\n",
                    encoding="utf-8",
                )
            elif "json" in cmd:
                out.write_text(
                    json.dumps({"language": "fr", "words": [], "segments": []}),
                    encoding="utf-8",
                )
            else:
                out.write_bytes(b"x")
        return 0, ""

    return fake_run


def _run_core(tmp_path: Path, monkeypatch, recorded: list, **job_kwargs):
    src = _src(tmp_path)
    monkeypatch.setattr(pipe, "_run", _fake_run_factory(recorded))
    monkeypatch.setattr(
        pipe, "_load_publish_cfg", lambda: {"video_source_path": str(tmp_path)}
    )
    monkeypatch.setattr(pipe, "_pr", lambda: "/nonexistent/prompt-bin")
    job = Job(
        job_id="test",
        source=str(src),
        prompt_title="t",
        prompt_summary="s",
        do_remove_silence=True,
        language="fr",
        model="medium",
        privacy="unlisted",
        use_modal=False,
        do_normalize_volume=True,
        do_add_signature=False,
        do_generate_thumbnail=False,
        skip_upload=True,
        steps=[Step(name=n) for n in STEP_NAMES],
        **job_kwargs,
    )
    return job


def _cmds_by_tool(recorded: list, tool: str, sub: str) -> list:
    return [c for c in recorded if tool in c[0] and sub in c]


async def _run_until_step2(job):
    """Run the pipeline; step 2's real `prompt` binary is missing by design,
    so the core raises after steps 0-1 have executed."""
    with pytest.raises(FileNotFoundError):
        await pipe._run_pipeline_core(job, 0)


def test_pipeline_rhythm_order_transcript_first(tmp_path: Path, monkeypatch):
    recorded: list = []
    job = _run_core(tmp_path, monkeypatch, recorded, rhythm_silence=True)

    import asyncio
    asyncio.run(_run_until_step2(job))

    json_cmds = _cmds_by_tool(recorded, "video", "extract-transcript")
    assert json_cmds and "--format" in json_cmds[0] and "json" in json_cmds[0]
    assert "--modal" not in json_cmds[0]

    cut_cmds = _cmds_by_tool(recorded, "video", "remove-silence")
    assert len(cut_cmds) == 1
    assert "--use-transcript" in cut_cmds[0]
    json_path = cut_cmds[0][cut_cmds[0].index("--use-transcript") + 1]
    assert json_path == job.files["transcript_json"]

    norm_cmds = _cmds_by_tool(recorded, "sound", "normalize-volume")
    assert len(norm_cmds) == 1
    assert norm_cmds[0][3] == job.files["no_silence"]  # normalized AFTER the cut

    ass_cmds = [c for c in json_cmds if "ass" in c]
    assert len(ass_cmds) == 1
    assert ass_cmds[0][2] == job.files.get("audio")  # ASS describes the final clip

    assert job.steps[0].status == "done"
    assert "Rhythm mode" in job.steps[0].output
    assert job.steps[1].status == "done"
    assert "Rhythm cut" in job.steps[1].output


def test_pipeline_default_order_unchanged(tmp_path: Path, monkeypatch):
    recorded: list = []
    job = _run_core(tmp_path, monkeypatch, recorded)

    import asyncio
    asyncio.run(_run_until_step2(job))

    cut_cmds = _cmds_by_tool(recorded, "video", "remove-silence")
    assert len(cut_cmds) == 1
    assert "--use-transcript" not in cut_cmds[0]

    norm_cmds = _cmds_by_tool(recorded, "sound", "normalize-volume")
    assert len(norm_cmds) == 1
    assert norm_cmds[0][3] == job.files["no_silence"]

    assert "transcript_json" not in job.files
    assert job.steps[0].status == "done"
    assert "Rhythm" not in job.steps[0].output


def test_pipeline_rhythm_passes_tuning_flags(tmp_path: Path, monkeypatch):
    recorded: list = []
    job = _run_core(
        tmp_path, monkeypatch, recorded,
        rhythm_silence=True,
        rhythm_params={"rhythm_pause_sentence": 0.6, "rhythm_crossfade": 0.005},
    )

    import asyncio
    asyncio.run(_run_until_step2(job))

    cut_cmds = _cmds_by_tool(recorded, "video", "remove-silence")
    assert len(cut_cmds) == 1
    assert "--pause-sentence" in cut_cmds[0]
    assert cut_cmds[0][cut_cmds[0].index("--pause-sentence") + 1] == "0.6"
    assert cut_cmds[0][cut_cmds[0].index("--crossfade") + 1] == "0.005"
    # Unset params are not passed: video config / code defaults apply.
    assert "--pause-comma" not in cut_cmds[0]


def test_pipeline_cut_time_runs_first(tmp_path: Path, monkeypatch):
    recorded: list = []
    job = _run_core(tmp_path, monkeypatch, recorded, cut_time="1:30")

    import asyncio
    asyncio.run(_run_until_step2(job))

    assert recorded[0][1] == "cut"
    assert "-t" in recorded[0] and "1:30" in recorded[0]
    assert job.files["cut"].endswith("_cut.mp4")
    assert job.cut_time == ""  # one-time: cleared so retry won't re-cut
    assert "✂ Cut at 1:30" in job.steps[0].output

    silence_cmds = _cmds_by_tool(recorded, "video", "remove-silence")
    assert len(silence_cmds) == 1
    assert silence_cmds[0][2] == job.files["cut"]  # silence step runs on the cut
    assert "--use-transcript" not in silence_cmds[0]


def test_pipeline_cut_time_before_rhythm_json(tmp_path: Path, monkeypatch):
    recorded: list = []
    job = _run_core(
        tmp_path, monkeypatch, recorded, rhythm_silence=True, cut_time="45",
    )

    import asyncio
    asyncio.run(_run_until_step2(job))

    kinds = [(c[1]) for c in recorded if "video" in c[0]]
    assert kinds[0] == "cut"
    json_cmds = _cmds_by_tool(recorded, "video", "extract-transcript")
    assert json_cmds and "json" in json_cmds[0]
    assert json_cmds[0][2] == job.files["cut"]  # transcript of the cut, not the source


def test_pipeline_invalid_cut_time_errors_step0(tmp_path: Path, monkeypatch):
    recorded: list = []
    job = _run_core(tmp_path, monkeypatch, recorded, cut_time="bogus")

    import asyncio
    asyncio.run(pipe._run_pipeline_core(job, 0))

    assert recorded == []
    assert job.steps[0].status == "error"
    assert "Invalid cut time" in job.steps[0].output
    assert job.status == "error"


def test_parse_timestamp():
    from webux.long_publish.utils import _parse_timestamp

    assert _parse_timestamp("1:30") == 90.0
    assert _parse_timestamp("00:01:30") == 90.0
    assert _parse_timestamp("45") == 45.0
    assert _parse_timestamp("") is None
    assert _parse_timestamp("bogus") is None
