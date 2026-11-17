"""Processing options (remove silence / burn subtitles / subtitle position /
Modal) must survive the pool queue.

The run form's three checkboxes used to be dropped by ``POST /pool/add`` and
hardcoded to ``True`` in ``_create_publish_job``, so every queued video ran all
three steps whatever the form said. These tests pin the whole chain:

    form → PoolAddRequest → add_to_pool → PoolItem → .publish-pool.json
        → worker → _create_publish_job → pipeline
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from webux.short_publish import pipeline
from webux.short_publish import pool as sp_pool
from webux.short_publish import register as sp_register
from webux.short_publish import utils as sp_utils
from webux.short_publish.models import STEP_NAMES, Job, Step


def _video(tmp_path: Path) -> Path:
    d = tmp_path / "clips"
    d.mkdir(exist_ok=True)
    v = d / "clip.mp4"
    v.write_text("x")
    return v


def _isolate_pool(monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_pool_auto_start", False)
    monkeypatch.setattr(sp_pool, "_save_pool_to_disk", lambda: None)
    monkeypatch.setattr(sp_pool, "start_pool", lambda: None)
    monkeypatch.setattr(sp_pool, "_get_video_duration_cli_sync", lambda p: 10.0)


# ── add_to_pool stores the three options ──────────────────────────────────

def test_add_to_pool_stores_processing_options(tmp_path, monkeypatch):
    _isolate_pool(monkeypatch)
    video = _video(tmp_path)

    assert sp_pool.add_to_pool(
        str(video),
        do_remove_silence=False,
        do_burn_subtitles=False,
        use_modal=False,
    )

    item = sp_pool._pool[0]
    assert item.do_remove_silence is False
    assert item.do_burn_subtitles is False
    assert item.use_modal is False


def test_add_to_pool_defaults_processing_options_to_true(tmp_path, monkeypatch):
    _isolate_pool(monkeypatch)
    video = _video(tmp_path)

    assert sp_pool.add_to_pool(str(video))

    item = sp_pool._pool[0]
    assert (item.do_remove_silence, item.do_burn_subtitles, item.use_modal) == (True, True, True)
    assert item.subtitle_position == "middle"


def test_add_to_pool_stores_subtitle_position(tmp_path, monkeypatch):
    _isolate_pool(monkeypatch)
    video = _video(tmp_path)

    assert sp_pool.add_to_pool(str(video), subtitle_position="bottom")

    assert sp_pool._pool[0].subtitle_position == "bottom"


# ── .publish-pool.json round trip ─────────────────────────────────────────

def test_pool_file_round_trip_keeps_processing_options(tmp_path, monkeypatch):
    pool_file = tmp_path / "clips" / ".publish-pool.json"
    pool_file.parent.mkdir()
    monkeypatch.setattr(sp_pool, "_pool_file", lambda: pool_file)
    monkeypatch.setattr(sp_pool, "_load_meta", lambda s: {})
    monkeypatch.setattr(sp_pool, "_pool", [
        sp_pool.PoolItem(
            source=str(pool_file.parent / "a.mp4"),
            do_remove_silence=False,
            do_burn_subtitles=False,
            subtitle_position="bottom",
            use_modal=False,
        ),
    ])

    sp_pool._save_pool_to_disk()
    saved = json.loads(pool_file.read_text(encoding="utf-8"))["items"][0]
    assert saved["do_remove_silence"] is False
    assert saved["do_burn_subtitles"] is False
    assert saved["subtitle_position"] == "bottom"
    assert saved["use_modal"] is False

    sp_pool._pool = []
    sp_pool._load_pool_from_disk()
    item = sp_pool._pool[0]
    assert (item.do_remove_silence, item.do_burn_subtitles, item.use_modal) == (False, False, False)
    assert item.subtitle_position == "bottom"


def test_legacy_pool_file_defaults_processing_options_to_true(tmp_path, monkeypatch):
    """A queue written before these keys existed keeps today's behaviour."""
    src = tmp_path / "clips"
    src.mkdir()
    pool_file = src / ".publish-pool.json"
    pool_file.write_text(json.dumps({"items": [
        {"source": str(src / "orig.mp4"), "status": "queued"},
    ]}))
    monkeypatch.setattr(sp_pool, "_pool_file", lambda: pool_file)
    monkeypatch.setattr(sp_pool, "_load_meta", lambda s: {})

    sp_pool._load_pool_from_disk()

    item = sp_pool._pool[0]
    assert (item.do_remove_silence, item.do_burn_subtitles, item.use_modal) == (True, True, True)
    assert item.subtitle_position == "middle"


def test_pool_state_exposes_processing_options(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_pool_auto_start", False)
    monkeypatch.setattr(sp_pool, "_get_video_duration_cli_sync", lambda p: 10.0)
    sp_pool._pool.append(sp_pool.PoolItem(
        source=str(tmp_path / "a.mp4"),
        status="queued",
        do_remove_silence=False,
        do_burn_subtitles=False,
        subtitle_position="top",
        use_modal=False,
    ))

    item = sp_pool.get_pool_state()["items"][0]

    assert item["do_remove_silence"] is False
    assert item["do_burn_subtitles"] is False
    assert item["subtitle_position"] == "top"
    assert item["use_modal"] is False


# ── _create_publish_job forwards the options to the Job ───────────────────

def test_create_publish_job_honours_processing_options(tmp_path, monkeypatch):
    video = _video(tmp_path)
    monkeypatch.setattr(sp_register, "_load_publish_cfg", lambda profile=None: {})
    monkeypatch.setattr(sp_register, "_load_meta", lambda s: {})

    job = sp_register._create_publish_job(
        str(video),
        do_remove_silence=False,
        do_burn_subtitles=False,
        subtitle_position="bottom",
        use_modal=False,
    )

    assert job.do_remove_silence is False
    assert job.do_burn_subtitles is False
    assert job.subtitle_position == "bottom"
    assert job.use_modal is False
    assert job.record_processing_options is True


def test_create_publish_job_defaults_processing_options_to_true(tmp_path, monkeypatch):
    video = _video(tmp_path)
    monkeypatch.setattr(sp_register, "_load_publish_cfg", lambda profile=None: {})
    monkeypatch.setattr(sp_register, "_load_meta", lambda s: {})

    job = sp_register._create_publish_job(str(video))

    assert (job.do_remove_silence, job.do_burn_subtitles, job.use_modal) == (True, True, True)
    assert job.subtitle_position == "middle"


# ── POST /pool/add forwards the three options ─────────────────────────────

def test_pool_add_endpoint_forwards_processing_options(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    captured: dict = {}

    def fake_add_to_pool(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return True

    monkeypatch.setattr(sp_register, "add_to_pool", fake_add_to_pool)
    app = FastAPI()
    app.include_router(sp_register.router)
    client = TestClient(app)

    r = client.post("/pool/add", json={
        "source": "/v/clip.mp4",
        "do_remove_silence": False,
        "do_burn_subtitles": False,
        "subtitle_position": "bottom",
        "use_modal": False,
    })

    assert r.status_code == 200, r.text
    assert captured["kwargs"]["do_remove_silence"] is False
    assert captured["kwargs"]["do_burn_subtitles"] is False
    assert captured["kwargs"]["subtitle_position"] == "bottom"
    assert captured["kwargs"]["use_modal"] is False


def test_pool_add_endpoint_defaults_processing_options_to_true(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    captured: dict = {}

    def fake_add_to_pool(*args, **kwargs):
        captured["kwargs"] = kwargs
        return True

    monkeypatch.setattr(sp_register, "add_to_pool", fake_add_to_pool)
    app = FastAPI()
    app.include_router(sp_register.router)
    client = TestClient(app)

    r = client.post("/pool/add", json={"source": "/v/clip.mp4"})

    assert r.status_code == 200, r.text
    assert captured["kwargs"]["do_remove_silence"] is True
    assert captured["kwargs"]["do_burn_subtitles"] is True
    assert captured["kwargs"]["subtitle_position"] == "middle"
    assert captured["kwargs"]["use_modal"] is True


def test_pool_add_endpoint_rejects_unknown_subtitle_position(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    def fake_add_to_pool(*args, **kwargs):  # must never be reached
        raise AssertionError("add_to_pool called with an invalid position")

    monkeypatch.setattr(sp_register, "add_to_pool", fake_add_to_pool)
    app = FastAPI()
    app.include_router(sp_register.router)
    client = TestClient(app)

    r = client.post("/pool/add", json={"source": "/v/clip.mp4", "subtitle_position": "sideways"})

    assert r.status_code == 400
    assert "sideways" in r.text


# ── pipeline actually skips the steps ─────────────────────────────────────
def _pipeline_job(tmp_path: Path, **flags) -> Job:
    video = _video(tmp_path)
    return Job(
        job_id="j",
        source=str(video),
        prompt_title="t",
        prompt_summary="s",
        do_remove_silence=flags.get("do_remove_silence", True),
        do_burn_subtitles=flags.get("do_burn_subtitles", True),
        subtitle_position=flags.get("subtitle_position", "middle"),
        use_modal=flags.get("use_modal", True),
        language="fr",
        model="medium",
        privacy="unlisted",
        do_charisma=False,
        do_add_signature=False,
        steps=[Step(name=n) for n in STEP_NAMES],
        record_processing_options=True,
    )


def _run_core(job: Job, tmp_path: Path, monkeypatch, from_step: int = 0):
    cmds: list[tuple[str, ...]] = []
    uploads: list[str] = []

    async def fake_tracked(job_, step, *cmd):
        cmds.append(cmd)
        return False

    async def fake_llm_and_upload(job_, transcript_path, final_video, from_step_=3):
        uploads.append(final_video)

    monkeypatch.setattr(pipeline, "_load_publish_cfg", lambda profile=None: {
        "video_source_path": str(tmp_path / "clips"),
    })
    monkeypatch.setattr(pipeline, "_run_tracked", fake_tracked)
    monkeypatch.setattr(pipeline, "_run_llm_and_upload", fake_llm_and_upload)
    monkeypatch.setattr(pipeline, "_ass_to_plain_text", lambda p: "")
    monkeypatch.setattr(pipeline, "_save_meta", lambda job_: None)
    monkeypatch.setattr(pipeline, "_get_video_duration", lambda p: _await(30.0))
    # The audio-analysis block spawns `sound normalize-volume measure` for real;
    # `echo` keeps it local, exit 0, and the JSON parse failure is harmless.
    monkeypatch.setattr(pipeline, "_sound", lambda: "echo")

    asyncio.run(pipeline._run_pipeline_core(job, from_step))
    return cmds, uploads


async def _await(value):
    return value


def test_pipeline_skips_silence_and_subtitles_when_disabled(tmp_path, monkeypatch):
    job = _pipeline_job(tmp_path, do_remove_silence=False, do_burn_subtitles=False, use_modal=False)

    cmds, uploads = _run_core(job, tmp_path, monkeypatch)

    flat = [c[1] for c in cmds if len(c) > 1]
    assert "remove-silence" not in flat
    assert "burn-subtitles" not in flat
    assert "extract-transcript" in flat  # transcript is independent of the two flags
    assert not any("--modal" in c for c in cmds)
    assert job.steps[0].status == "done"
    assert "Remove silence disabled" in job.steps[0].output
    assert job.steps[2].status == "skipped"
    assert "subtitles disabled" in job.steps[2].output
    assert uploads  # pipeline continued to the LLM/upload stage


def test_pipeline_runs_silence_and_subtitles_when_enabled(tmp_path, monkeypatch):
    job = _pipeline_job(tmp_path, do_remove_silence=True, do_burn_subtitles=True, use_modal=False)

    cmds, _ = _run_core(job, tmp_path, monkeypatch)

    flat = [c[1] for c in cmds if len(c) > 1]
    assert "remove-silence" in flat
    assert "burn-subtitles" in flat


def test_pipeline_forwards_modal_flag(tmp_path, monkeypatch):
    job = _pipeline_job(tmp_path, do_remove_silence=True, do_burn_subtitles=True, use_modal=True)

    cmds, _ = _run_core(job, tmp_path, monkeypatch)

    by_sub = {c[1]: c for c in cmds if len(c) > 1}
    assert "--modal" in by_sub["remove-silence"]
    assert "--modal" in by_sub["burn-subtitles"]


def test_pipeline_forwards_subtitle_position(tmp_path, monkeypatch):
    job = _pipeline_job(
        tmp_path, do_remove_silence=False, do_burn_subtitles=True,
        subtitle_position="bottom", use_modal=False,
    )

    cmds, _ = _run_core(job, tmp_path, monkeypatch)

    burn = next(c for c in cmds if len(c) > 1 and c[1] == "burn-subtitles")
    assert burn[burn.index("--position") + 1] == "bottom"


# ── meta log traceability ─────────────────────────────────────────────────

def _meta_job(source: str, *, record: bool, **flags) -> Job:
    return Job(
        job_id="j",
        source=source,
        prompt_title="t",
        prompt_summary="s",
        do_remove_silence=flags.get("do_remove_silence", True),
        do_burn_subtitles=flags.get("do_burn_subtitles", True),
        subtitle_position=flags.get("subtitle_position", "middle"),
        use_modal=flags.get("use_modal", True),
        language="fr",
        model="medium",
        privacy="unlisted",
        steps=[Step(name=n) for n in STEP_NAMES],
        record_processing_options=record,
    )


def test_meta_records_processing_options(tmp_path):
    video = _video(tmp_path)
    job = _meta_job(str(video), record=True, do_remove_silence=False,
                    do_burn_subtitles=False, subtitle_position="bottom", use_modal=False)

    sp_utils._save_meta(job)

    meta = json.loads((video.parent / "clip-meta.json").read_text(encoding="utf-8"))
    assert meta["do_remove_silence"] is False
    assert meta["do_burn_subtitles"] is False
    assert meta["subtitle_position"] == "bottom"
    assert meta["use_modal"] is False


def test_meta_keeps_previous_options_for_jobs_that_do_not_own_them(tmp_path):
    """Resume / redo post-publish force the flags off; they must not rewrite the
    values the original run recorded."""
    video = _video(tmp_path)
    meta_path = video.parent / "clip-meta.json"
    meta_path.write_text(json.dumps({
        "source": str(video),
        "do_remove_silence": False,
        "do_burn_subtitles": True,
        "subtitle_position": "bottom",
        "use_modal": False,
    }), encoding="utf-8")

    job = _meta_job(str(video), record=False, do_remove_silence=False,
                    do_burn_subtitles=False, subtitle_position="top", use_modal=True)
    sp_utils._save_meta(job)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["do_remove_silence"] is False
    assert meta["do_burn_subtitles"] is True   # not overwritten by the resume's False
    assert meta["subtitle_position"] == "bottom"  # not overwritten by the resume's "top"
    assert meta["use_modal"] is False          # not overwritten by the resume's True


# ── subtitle position: validation + run form contract ─────────────────────

SHORT_HTML = Path(__file__).parent.parent / "webux" / "short_publish" / "frontend.html"


def test_normalize_subtitle_position():
    import pytest

    from webux.short_publish.models import normalize_subtitle_position

    assert normalize_subtitle_position(None) == "middle"
    assert normalize_subtitle_position("") == "middle"
    assert normalize_subtitle_position(" Bottom ") == "bottom"
    assert normalize_subtitle_position("top-left") == "top-left"
    with pytest.raises(ValueError):
        normalize_subtitle_position("sideways")


def test_run_form_exposes_subtitle_position():
    """The position select defaults to middle for every newly proposed video."""
    html = SHORT_HTML.read_text(encoding="utf-8")

    assert 'id="subtitlePosition"' in html
    for pos in ("middle", "bottom", "top", "top-left"):
        assert f'<option value="{pos}"' in html
    assert '<option value="middle" selected>' in html
    # A new video must always reset to the default placement...
    assert "resetSubtitlePosition();" in html
    # ...so the choice is per-video and deliberately NOT in the persisted UI state.
    assert "'cutTime','removeSilence','burnSubtitles','useModal'\n];" in html
    # ...and every payload that can start/queue a run forwards it.
    assert html.count(
        "subtitle_position: document.getElementById('subtitlePosition').value"
    ) == 4
