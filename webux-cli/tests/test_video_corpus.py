"""Tests for the corpus add helper shared by both publish pipelines."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import webux.long_publish.register as long_reg
import webux.short_publish.register as short_reg
import webux.video_corpus as vc


STUB = '''#!/usr/bin/env python3
import json, os, shutil, sys

args = sys.argv[1:]
with open(os.environ["ARGV_LOG"], "w", encoding="utf-8") as fh:
    fh.write("\\n".join(args))
if "--transcript-file" in args:
    shutil.copyfile(args[args.index("--transcript-file") + 1], os.environ["TRANSCRIPT_COPY"])
if "--description-file" in args:
    shutil.copyfile(args[args.index("--description-file") + 1], os.environ["DESC_COPY"])
if int(os.environ.get("STUB_EXIT", "0")):
    print("boom", file=sys.stderr)
    sys.exit(int(os.environ["STUB_EXIT"]))
print(json.dumps({"handle": "youtube:abc123", "indexed": True}))
'''


def _stub(tmp_path: Path) -> Path:
    path = tmp_path / "corpus"
    path.write_text(STUB, encoding="utf-8")
    path.chmod(0o755)
    return path


def _job(**overrides):
    base = dict(
        files={},
        transcript_text="",
        title="",
        video_url="",
        description="",
        privacy="unlisted",
        do_add_to_corpus=True,
        skip_upload=False,
        stop_requested=False,
        corpus_video_id="",
        corpus_handle="",
        profile="default",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _step() -> SimpleNamespace:
    return SimpleNamespace(output="Uploaded")


def _env(tmp_path: Path, **extra: str) -> dict:
    env = dict(os.environ)
    env.update(
        ARGV_LOG=str(tmp_path / "argv.txt"),
        TRANSCRIPT_COPY=str(tmp_path / "transcript-copy.txt"),
        DESC_COPY=str(tmp_path / "desc-copy.txt"),
    )
    env.update(extra)
    return env


def _client(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# --- transcript_text -------------------------------------------------------


def test_transcript_text_prefers_file(tmp_path: Path):
    transcript = tmp_path / "t.txt"
    transcript.write_text("from file", encoding="utf-8")
    job = _job(files={"transcript_txt": str(transcript)}, transcript_text="from job")
    assert vc.transcript_text(job) == "from file"


def test_transcript_text_falls_back_to_job_text(tmp_path: Path):
    job = _job(files={"transcript_txt": str(tmp_path / "missing.txt")}, transcript_text=" from job ")
    assert vc.transcript_text(job) == "from job"


def test_transcript_text_rejects_placeholders():
    assert vc.transcript_text(_job(transcript_text="(transcript unavailable)")) == ""
    assert vc.transcript_text(_job(transcript_text="(no transcript produced)")) == ""
    assert vc.transcript_text(_job(transcript_text="   ")) == ""


# --- maybe_add_to_corpus: skip conditions ---------------------------------


def _forbid_run(monkeypatch):
    async def _boom(*args, **kwargs):
        raise AssertionError("corpus add must not run")

    monkeypatch.setattr(vc, "_run_corpus_add", _boom)


def test_skips_when_flag_disabled(monkeypatch):
    _forbid_run(monkeypatch)
    job = _job(do_add_to_corpus=False, transcript_text="hello")
    step = _step()
    result = asyncio.run(
        vc.maybe_add_to_corpus(job, "abcdefghijk", step, env={})
    )
    assert result.ok is False
    assert job.corpus_video_id == ""
    assert step.output == "Uploaded"


def test_skips_on_skip_upload_or_missing_id_or_stop(monkeypatch):
    _forbid_run(monkeypatch)
    for job, vid in (
        (_job(skip_upload=True, transcript_text="hello"), "abcdefghijk"),
        (_job(transcript_text="hello"), ""),
        (_job(stop_requested=True, transcript_text="hello"), "abcdefghijk"),
    ):
        result = asyncio.run(vc.maybe_add_to_corpus(job, vid, _step(), env={}))
        assert result.ok is False


def test_idempotent_when_video_already_indexed(monkeypatch):
    _forbid_run(monkeypatch)
    job = _job(
        transcript_text="hello",
        corpus_video_id="abcdefghijk",
        corpus_handle="youtube:abc123",
    )
    result = asyncio.run(
        vc.maybe_add_to_corpus(job, "abcdefghijk", _step(), env={})
    )
    assert result.ok is True
    assert result.already is True
    assert result.handle == "youtube:abc123"


# --- maybe_add_to_corpus: outcomes ----------------------------------------


def test_warns_without_transcript(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path)
    monkeypatch.setattr(vc, "_corpus", lambda: str(stub))
    job = _job(title="T", transcript_text="(transcript unavailable)")
    step = _step()
    saved = []

    result = asyncio.run(
        vc.maybe_add_to_corpus(
            job,
            "abcdefghijk",
            step,
            env=_env(tmp_path),
            save_meta=lambda: saved.append(True),
        )
    )
    assert result.ok is False
    assert "no transcript" in result.error
    assert "⚠ Corpus add failed" in step.output
    assert job.corpus_video_id == ""
    assert saved == [True]
    assert not Path(_env(tmp_path)["ARGV_LOG"]).exists()


def test_success_runs_add_and_records_handle(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path)
    monkeypatch.setattr(vc, "_corpus", lambda: str(stub))
    job = _job(
        title="My video",
        transcript_text="hello transcript",
        description="the description",
        privacy="unlisted",
    )
    step = _step()
    saved = []

    result = asyncio.run(
        vc.maybe_add_to_corpus(
            job,
            "abcdefghijk",
            step,
            env=_env(tmp_path),
            duration=61.2,
            save_meta=lambda: saved.append(True),
        )
    )

    assert result.ok is True
    assert result.handle == "youtube:abc123"
    assert job.corpus_video_id == "abcdefghijk"
    assert job.corpus_handle == "youtube:abc123"
    assert "➕ Added to corpus: youtube:abc123" in step.output
    assert saved == [True]

    argv = (tmp_path / "argv.txt").read_text(encoding="utf-8").splitlines()
    # The profile is passed before the subcommand (corpus group option), so the
    # shared corpus tags the entry with the publish profile.
    assert argv[:2] == ["--profile", "default"]
    assert argv[2:4] == ["add", "--source"]
    assert argv[argv.index("--id") + 1] == "abcdefghijk"
    assert argv[argv.index("--url") + 1] == "https://www.youtube.com/watch?v=abcdefghijk"
    assert argv[argv.index("--title") + 1] == "My video"
    assert argv[argv.index("--privacy") + 1] == "unlisted"
    assert argv[argv.index("--duration") + 1] == "61"
    assert argv[argv.index("--format") + 1] == "json"
    assert (tmp_path / "transcript-copy.txt").read_text(encoding="utf-8") == "hello transcript"
    assert (tmp_path / "desc-copy.txt").read_text(encoding="utf-8") == "the description"


def test_failure_is_non_blocking(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path)
    monkeypatch.setattr(vc, "_corpus", lambda: str(stub))
    job = _job(title="T", transcript_text="hello")
    step = _step()
    saved = []

    result = asyncio.run(
        vc.maybe_add_to_corpus(
            job,
            "abcdefghijk",
            step,
            env=_env(tmp_path, STUB_EXIT="3"),
            save_meta=lambda: saved.append(True),
        )
    )

    assert result.ok is False
    assert "boom" in result.error
    assert "⚠ Corpus add failed (non-blocking)" in step.output
    assert job.corpus_video_id == ""
    assert saved == [True]


def test_missing_cli_is_reported_not_raised(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(vc, "_corpus", lambda: str(tmp_path / "does-not-exist"))
    job = _job(title="T", transcript_text="hello")
    step = _step()

    result = asyncio.run(
        vc.maybe_add_to_corpus(job, "abcdefghijk", step, env=_env(tmp_path))
    )
    assert result.ok is False
    assert "cannot run corpus CLI" in result.error
    assert "⚠ Corpus add failed" in step.output


def test_unexpected_exception_never_escapes(tmp_path: Path, monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(vc, "_run_corpus_add", _boom)
    job = _job(title="T", transcript_text="hello")
    step = _step()

    result = asyncio.run(
        vc.maybe_add_to_corpus(job, "abcdefghijk", step, env=_env(tmp_path))
    )
    assert result.ok is False
    assert "kaboom" in result.error
    assert "⚠ Corpus add failed" in step.output


# --- API wiring ------------------------------------------------------------


def test_long_start_passes_corpus_flag(tmp_path: Path, monkeypatch):
    src = tmp_path / "clip.webm"
    src.write_bytes(b"x")
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

    monkeypatch.setattr(long_reg, "_run_pipeline_from", fake_from)
    monkeypatch.setattr(long_reg, "_run_job_safely", fake_safe)

    with _client(long_reg.router) as client:
        response = client.post(
            "/start",
            json={
                "source": str(src),
                "prompt_title": "t",
                "prompt_summary": "s",
                "do_add_to_corpus": False,
            },
        )
    assert response.status_code == 200, response.text
    job = long_reg._jobs[response.json()["job_id"]]
    assert job.do_add_to_corpus is False


def test_long_start_defaults_corpus_flag_on(tmp_path: Path, monkeypatch):
    src = tmp_path / "clip.webm"
    src.write_bytes(b"x")

    def fake_from(job, from_step):
        async def _inner():
            return None

        return _inner()

    def fake_safe(coro, job):
        coro.close()

        async def _done():
            return None

        return _done()

    monkeypatch.setattr(long_reg, "_run_pipeline_from", fake_from)
    monkeypatch.setattr(long_reg, "_run_job_safely", fake_safe)

    with _client(long_reg.router) as client:
        response = client.post(
            "/start",
            json={"source": str(src), "prompt_title": "t", "prompt_summary": "s"},
        )
    assert response.status_code == 200, response.text
    job = long_reg._jobs[response.json()["job_id"]]
    assert job.do_add_to_corpus is True


def test_short_pool_add_passes_corpus_flag(monkeypatch):
    captured = {}

    def fake_add(*args, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(short_reg, "add_to_pool", fake_add)
    with _client(short_reg.router) as client:
        response = client.post(
            "/pool/add",
            json={"source": "/tmp/clip.webm", "do_add_to_corpus": False},
        )
    assert response.status_code == 200, response.text
    assert captured["do_add_to_corpus"] is False
