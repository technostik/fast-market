"""Re-upload to another channel: reuse steps 0-3 from the meta log, start at
step 4 with the target profile, reset upload-specific state, and re-apply the
target channel's description signature."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import webux.short_publish.register as short_reg
from webux.short_publish.models import STEP_NAMES, Job, Step
from webux.short_publish.utils import _load_meta, _save_meta

OLD_SIG = "OLD SIGNATURE"
NEW_SIG = "NEW SIGNATURE"
RAW = "BODY OF THE DESCRIPTION"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(short_reg.router)
    return TestClient(app)


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    profiles = tmp_path / "profiles"
    (profiles / "old").mkdir(parents=True)
    (profiles / "new").mkdir(parents=True)

    monkeypatch.setattr(short_reg, "get_profiles_config_base", lambda: profiles)
    monkeypatch.setattr(short_reg, "_is_busy", lambda: False)
    monkeypatch.setattr(short_reg, "_jobs", {})

    async def _noop(job, from_step):  # never touch subprocesses in tests
        return None

    monkeypatch.setattr(short_reg, "_run_pipeline_from", _noop)

    cfg = {
        "old": {"signature": OLD_SIG, "privacy": "unlisted"},
        "new": {
            "signature": NEW_SIG,
            "privacy": "public",
            "post_publish_script": "/tmp/post.sh",
            "short_pinned_comment_enabled": True,
            "short_pinned_comment_text": "NEW COMMENT",
        },
    }
    monkeypatch.setattr(
        short_reg, "_load_publish_cfg", lambda profile=None: cfg.get(profile or "", {})
    )

    src = tmp_path / "clip.mp4"
    src.write_bytes(b"source")
    final = tmp_path / "My Title.mp4"
    final.write_bytes(b"final")

    meta = {
        "source": str(src),
        "profile": "old",
        "title": "My Title",
        "description": f"{RAW}\n\n{OLD_SIG}",
        "description_raw": RAW,
        "completed_steps": [0, 1, 2, 3, 4, 5],
        "skipped_steps": [6],
        "files": {"final_video": str(final)},
        "video_url": "https://www.youtube.com/shorts/OLDID",
        "studio_url": "https://studio.youtube.com/video/OLDID/edit",
        "pinned_comment_id": "old-comment",
        "pinned_comment_url": "https://www.youtube.com/watch?v=OLDID&lc=old-comment",
        "description_prefix": "Prefix text",
        "source_urls": ["https://example.com"],
        "uploads": [
            {
                "profile": "old",
                "video_url": "https://www.youtube.com/shorts/OLDID",
                "studio_url": "https://studio.youtube.com/video/OLDID/edit",
            }
        ],
    }
    (tmp_path / "clip-meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return {"src": src, "final": final, "meta": meta, "dir": tmp_path}


def _reupload(client: TestClient, env, **overrides):
    body = {"source": str(env["src"]), "profile": "new"}
    body.update(overrides)
    return client.post("/reupload", json=body)


def test_reupload_reuses_meta_and_resets_upload_state(env):
    with _client() as client:
        r = _reupload(client, env)
        assert r.status_code == 200, r.text
        data = r.json()
        job = short_reg._jobs[data["job_id"]]

    assert job.profile == "new"
    assert job.title == "My Title"
    assert job.files["final_video"] == str(env["final"])
    assert job.pinned_comment_id == ""
    assert job.pinned_comment_url == ""
    assert job.privacy == "public"
    assert job.skip_upload is False
    assert job.do_ignore_post_publish is False
    # Steps 0-3 are reused, step 4 restarts.
    assert [s.status for s in job.steps[:4]] == ["done"] * 4
    assert job.steps[4].status == "pending"
    # Target channel signature replaces the old one, prefix/sources preserved.
    assert job.description_raw == RAW
    assert job.description == f"Prefix text\n\nSources:\n- https://example.com\n\n{RAW}\n\n{NEW_SIG}"
    assert data["previous"]["profile"] == "old"
    assert data["previous"]["video_url"] == "https://www.youtube.com/shorts/OLDID"


def test_reupload_works_without_the_original_source(env):
    env["src"].unlink()
    with _client() as client:
        r = _reupload(client, env)
        assert r.status_code == 200, r.text


def test_reupload_legacy_meta_strips_old_signature(env):
    meta = dict(env["meta"])
    meta.pop("description_raw", None)
    (env["dir"] / "clip-meta.json").write_text(json.dumps(meta), encoding="utf-8")

    with _client() as client:
        r = _reupload(client, env)
        assert r.status_code == 200, r.text
        job = short_reg._jobs[r.json()["job_id"]]

    assert RAW in job.description
    assert OLD_SIG not in job.description
    assert job.description.endswith(NEW_SIG)


def test_reupload_skips_post_publish_when_asked(env):
    with _client() as client:
        r = _reupload(client, env, run_post_publish=False)
        assert r.status_code == 200, r.text
        job = short_reg._jobs[r.json()["job_id"]]

    assert job.do_ignore_post_publish is True


def test_reupload_rejects_while_busy(env, monkeypatch):
    monkeypatch.setattr(short_reg, "_is_busy", lambda: True)
    with _client() as client:
        r = _reupload(client, env)
    assert r.status_code == 409


def test_reupload_requires_final_video(env):
    meta = dict(env["meta"])
    meta["files"] = {"final_video": str(env["dir"] / "gone.mp4")}
    (env["dir"] / "clip-meta.json").write_text(json.dumps(meta), encoding="utf-8")

    with _client() as client:
        r = _reupload(client, env)
    assert r.status_code == 400
    assert "final video" in r.json()["detail"].lower()


def test_reupload_requires_a_previous_upload(env):
    meta = dict(env["meta"])
    meta["completed_steps"] = [0, 1, 2, 3]
    (env["dir"] / "clip-meta.json").write_text(json.dumps(meta), encoding="utf-8")

    with _client() as client:
        r = _reupload(client, env)
    assert r.status_code == 400
    assert "not been uploaded" in r.json()["detail"]


def test_reupload_rejects_unknown_profile(env):
    with _client() as client:
        r = _reupload(client, env, profile="does_not_exist")
    assert r.status_code == 400
    assert "Unknown target profile" in r.json()["detail"]


def test_reupload_pipeline_reaches_upload_and_records_history(env, monkeypatch):
    import webux.short_publish.pipeline as pipeline

    async def fake_run(job, step, *cmd):
        return 0, "https://www.youtube.com/watch?v=NEWID"

    async def fake_duration(path):
        return 120.0

    monkeypatch.setattr(pipeline, "_run", fake_run)
    monkeypatch.setattr(pipeline, "_get_video_duration", fake_duration)
    monkeypatch.setattr(pipeline, "_load_publish_cfg", short_reg._load_publish_cfg)

    with _client() as client:
        r = _reupload(client, env, run_post_publish=False, do_pinned_comment=False)
        assert r.status_code == 200, r.text
        job = short_reg._jobs[r.json()["job_id"]]

    asyncio.run(pipeline._run_pipeline_core(job, 4))

    assert job.status == "done"
    assert job.video_url == "https://www.youtube.com/shorts/NEWID"
    assert job.steps[3].status == "done"  # reuse must not downgrade it to skipped
    assert job.steps[4].status == "done"

    meta = _load_meta(str(env["src"]))
    assert meta["video_url"] == "https://www.youtube.com/shorts/NEWID"
    assert meta["profile"] == "new"
    assert [u["profile"] for u in meta["uploads"]] == ["old", "new"]
    assert meta.get("pinned_comment_id") in (None, "")  # old channel's comment not inherited


def _new_job(
    source: Path,
    video_url: str,
    profile: str,
    privacy: str = "unlisted",
    pinned_comment_id: str = "",
) -> Job:
    studio = (
        f"https://studio.youtube.com/video/{video_url.rsplit('/', 1)[-1]}/edit"
        if video_url
        else ""
    )
    return Job(
        job_id="job",
        source=str(source),
        profile=profile,
        prompt_title="t",
        prompt_summary="s",
        do_remove_silence=False,
        do_burn_subtitles=False,
        language="fr",
        model="medium",
        privacy=privacy,
        steps=[Step(name=n) for n in STEP_NAMES],
        video_url=video_url,
        studio_url=studio,
        title="Title",
        pinned_comment_id=pinned_comment_id,
    )


def test_meta_upload_history_keeps_every_channel(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")

    _save_meta(_new_job(src, "https://www.youtube.com/shorts/AAA", "old"))
    # Saving the same upload again must not duplicate the entry.
    _save_meta(_new_job(src, "https://www.youtube.com/shorts/AAA", "old", privacy="private"))
    uploads = _load_meta(str(src))["uploads"]
    assert len(uploads) == 1
    assert uploads[0]["profile"] == "old"
    assert uploads[0]["privacy"] == "private"

    _save_meta(_new_job(src, "https://www.youtube.com/shorts/BBB", "new"))
    uploads = _load_meta(str(src))["uploads"]
    assert [u["profile"] for u in uploads] == ["old", "new"]
    assert _load_meta(str(src))["profile"] == "new"


def test_meta_keeps_previous_upload_until_new_one_succeeds(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    old_url = "https://www.youtube.com/shorts/AAA"
    _save_meta(_new_job(src, old_url, "old", pinned_comment_id="old-comment"))

    # Re-upload job before its upload step: nothing new to record yet.
    _save_meta(_new_job(src, "", "new"))
    meta = _load_meta(str(src))
    assert meta["video_url"] == old_url
    assert meta["pinned_comment_id"] == "old-comment"

    # After the new upload succeeds, the old pinned comment id is not inherited.
    _save_meta(_new_job(src, "https://www.youtube.com/shorts/BBB", "new"))
    meta = _load_meta(str(src))
    assert meta["video_url"].endswith("BBB")
    assert "pinned_comment_id" not in meta


def test_meta_history_survives_saves_without_video_url(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    _save_meta(_new_job(src, "https://www.youtube.com/shorts/AAA", "old"))

    # A later step-save (no video_url yet) must not erase the history.
    job = _new_job(src, "", "new")
    _save_meta(job)
    uploads = _load_meta(str(src))["uploads"]
    assert [u["profile"] for u in uploads] == ["old"]
