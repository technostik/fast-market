"""Telegram alerts for short/long publish: config, endpoints and pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import webux.long_publish.pipeline as long_pipe
import webux.long_publish.register as long_reg
import webux.short_publish.pipeline as short_pipe
import webux.short_publish.register as short_reg
from webux.long_publish.models import Job as LongJob
from webux.long_publish.models import Step as LongStep
from webux.short_publish.models import Job as ShortJob
from webux.short_publish.models import Step as ShortStep
from common.webux.telegram_targets import (
    DEFAULT_LONG_ALERT_TEMPLATE,
    DEFAULT_SHORT_ALERT_TEMPLATE,
    render_alert,
)


def _short_job(tmp_path: Path, **kw) -> ShortJob:
    return ShortJob(
        job_id="job-short",
        source=str(tmp_path / "clip.mp4"),
        prompt_title="",
        prompt_summary="",
        do_remove_silence=False,
        do_burn_subtitles=False,
        language="fr",
        model="medium",
        privacy="unlisted",
        **kw,
    )


def _long_job(tmp_path: Path, **kw) -> LongJob:
    return LongJob(
        job_id="job-long",
        source=str(tmp_path / "clip.mp4"),
        prompt_title="",
        prompt_summary="",
        do_remove_silence=False,
        language="fr",
        model="medium",
        privacy="unlisted",
        **kw,
    )


class _Proc:
    def __init__(self, returncode: int = 0, stderr: bytes = b""):
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self):
        return b'{"message_id": 1, "status": "success"}', self._stderr


def _fake_exec(calls: list[tuple], proc: _Proc):
    async def fake(*args, **kwargs):
        calls.append(args)
        return proc

    return fake


def _wrap(job, step):
    return job.steps[step]


# ── Pipeline behaviour ─────────────────────────────────────────────────────

def test_short_alert_cfg_tristate():
    assert short_pipe._telegram_alert_cfg(
        _short_job(Path("/tmp")), {"short_telegram_alert_enabled": True}
    ) == (True, "")
    assert short_pipe._telegram_alert_cfg(
        _short_job(Path("/tmp"), do_telegram_alert=False),
        {"short_telegram_alert_enabled": True},
    ) == (False, "")
    assert short_pipe._telegram_alert_cfg(
        _short_job(Path("/tmp"), do_telegram_alert=True),
        {"short_telegram_alert_enabled": False, "telegram_alert_target": "t1"},
    ) == (True, "t1")


def test_short_alert_sends_with_target(monkeypatch, tmp_path):
    job = _short_job(
        tmp_path,
        do_telegram_alert=True,
        title="Mon <Short>",
        video_url="https://youtu.be/abc",
    )
    step = ShortStep(name="Upload to YouTube")
    monkeypatch.setattr(
        short_pipe,
        "_load_publish_cfg",
        lambda profile=None: {"telegram_alert_target": "technostik"},
    )
    calls: list[tuple] = []
    monkeypatch.setattr(
        short_pipe.asyncio, "create_subprocess_exec", _fake_exec(calls, _Proc())
    )

    asyncio.run(short_pipe._maybe_send_telegram_alert(job, "abc", step))

    assert calls, "message CLI should have been invoked"
    args = calls[0]
    assert "alert" in args
    text = args[args.index("alert") + 1]
    assert "Mon &lt;Short&gt;" in text  # HTML-escaped for parse_mode=HTML
    assert args[args.index("--target") + 1] == "technostik"
    assert job.telegram_alert_sent is True
    assert "Telegram alert sent" in step.output


def test_render_alert_default_template_escapes_title():
    text = render_alert(
        "",
        default=DEFAULT_SHORT_ALERT_TEMPLATE,
        title="Mon <Short> & co",
        url="https://youtu.be/abc",
        video_id="abc",
    )
    assert text == "✅ Short publié : Mon &lt;Short&gt; &amp; co\nhttps://youtu.be/abc"


def test_render_alert_custom_template_and_unknown_placeholders():
    text = render_alert(
        "<b>{title}</b>\n{url}\nid={video_id} {unknown} {",
        default=DEFAULT_LONG_ALERT_TEMPLATE,
        title="Titre",
        url="https://youtu.be/abc",
        video_id="abc",
    )
    # Unknown placeholders and stray braces stay literal (never a KeyError).
    assert text == "<b>Titre</b>\nhttps://youtu.be/abc\nid=abc {unknown} {"


def test_render_alert_falls_back_to_video_id_when_title_empty():
    assert (
        render_alert("{title}", default="d", title="  ", url="u", video_id="abc")
        == "abc"
    )
    assert render_alert("   ", default="d", title="t", url="u") == "d"


def test_short_alert_uses_configured_template(monkeypatch, tmp_path):
    job = _short_job(
        tmp_path,
        do_telegram_alert=True,
        title="Mon Short",
        video_url="https://youtu.be/abc",
    )
    step = ShortStep(name="Upload to YouTube")
    monkeypatch.setattr(
        short_pipe,
        "_load_publish_cfg",
        lambda profile=None: {
            "telegram_alert_target": "t1",
            "short_telegram_alert_template": "<b>{title}</b>\n{url} ({video_id})",
        },
    )
    calls: list[tuple] = []
    monkeypatch.setattr(
        short_pipe.asyncio, "create_subprocess_exec", _fake_exec(calls, _Proc())
    )

    asyncio.run(short_pipe._maybe_send_telegram_alert(job, "abc", step))

    text = calls[0][calls[0].index("alert") + 1]
    assert text == "<b>Mon Short</b>\nhttps://youtu.be/abc (abc)"


def test_long_alert_uses_configured_template(monkeypatch, tmp_path):
    job = _long_job(
        tmp_path,
        do_telegram_alert=True,
        title="Ma vidéo",
        video_url="https://youtu.be/x",
    )
    step = LongStep(name="Upload to YouTube")
    monkeypatch.setattr(
        long_pipe,
        "_load_publish_cfg",
        lambda profile=None: {
            "telegram_alert_target": "t1",
            "long_telegram_alert_template": "{title} → {url}",
        },
    )
    calls: list[tuple] = []
    monkeypatch.setattr(
        long_pipe.asyncio, "create_subprocess_exec", _fake_exec(calls, _Proc())
    )

    asyncio.run(long_pipe._maybe_send_telegram_alert(job, "x", step))
    text = calls[0][calls[0].index("alert") + 1]
    assert text == "Ma vidéo → https://youtu.be/x"


def test_short_alert_skips_when_disabled(monkeypatch, tmp_path):
    job = _short_job(tmp_path, do_telegram_alert=False)
    step = ShortStep(name="Upload to YouTube")
    monkeypatch.setattr(
        short_pipe,
        "_load_publish_cfg",
        lambda profile=None: {
            "short_telegram_alert_enabled": True,
            "telegram_alert_target": "t1",
        },
    )
    calls: list[tuple] = []
    monkeypatch.setattr(
        short_pipe.asyncio, "create_subprocess_exec", _fake_exec(calls, _Proc())
    )

    asyncio.run(short_pipe._maybe_send_telegram_alert(job, "abc", step))
    assert calls == []
    assert job.telegram_alert_sent is False


def test_short_alert_missing_target_is_a_warning(monkeypatch, tmp_path):
    job = _short_job(tmp_path, do_telegram_alert=True)
    step = ShortStep(name="Upload to YouTube")
    monkeypatch.setattr(short_pipe, "_load_publish_cfg", lambda profile=None: {})
    calls: list[tuple] = []
    monkeypatch.setattr(
        short_pipe.asyncio, "create_subprocess_exec", _fake_exec(calls, _Proc())
    )

    asyncio.run(short_pipe._maybe_send_telegram_alert(job, "abc", step))
    assert calls == []
    assert "no telegram_alert_target" in step.output


def test_short_alert_failure_is_non_blocking(monkeypatch, tmp_path):
    job = _short_job(tmp_path, do_telegram_alert=True)
    step = ShortStep(name="Upload to YouTube")
    monkeypatch.setattr(
        short_pipe,
        "_load_publish_cfg",
        lambda profile=None: {"telegram_alert_target": "t1"},
    )
    calls: list[tuple] = []
    monkeypatch.setattr(
        short_pipe.asyncio,
        "create_subprocess_exec",
        _fake_exec(calls, _Proc(returncode=2, stderr=b"boom")),
    )

    asyncio.run(short_pipe._maybe_send_telegram_alert(job, "abc", step))
    assert job.telegram_alert_sent is False
    assert "Telegram alert failed" in step.output
    assert "boom" in step.output


def test_long_alert_uses_long_enabled_key_and_message(monkeypatch, tmp_path):
    job = _long_job(tmp_path, title="Ma vidéo", video_url="https://youtu.be/x")
    step = LongStep(name="Upload to YouTube")
    monkeypatch.setattr(
        long_pipe,
        "_load_publish_cfg",
        lambda profile=None: {
            "long_telegram_alert_enabled": True,
            "telegram_alert_target": "joriel",
            "short_telegram_alert_enabled": False,
        },
    )
    calls: list[tuple] = []
    monkeypatch.setattr(
        long_pipe.asyncio, "create_subprocess_exec", _fake_exec(calls, _Proc())
    )

    asyncio.run(long_pipe._maybe_send_telegram_alert(job, "x", step))
    args = calls[0]
    assert "Vidéo publiée" in args[args.index("alert") + 1]
    assert args[args.index("--target") + 1] == "joriel"


# ── Job creation honours the config fallback ───────────────────────────────

def test_short_create_job_uses_telegram_config(monkeypatch, tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(
        short_reg,
        "_load_publish_cfg",
        lambda profile=None: {"short_telegram_alert_enabled": True},
    )
    monkeypatch.setattr(short_reg, "_load_meta", lambda source: {})

    job = short_reg._create_publish_job(str(src))
    assert job.do_telegram_alert is True

    job2 = short_reg._create_publish_job(str(src), do_telegram_alert=False)
    assert job2.do_telegram_alert is False


def test_long_create_job_uses_telegram_config(monkeypatch, tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(
        long_reg,
        "_load_publish_cfg",
        lambda profile=None: {"long_telegram_alert_enabled": True},
    )
    monkeypatch.setattr(long_reg, "_load_meta", lambda source: {})

    job = long_reg._create_publish_job(str(src))
    assert job.do_telegram_alert is True


# ── API ────────────────────────────────────────────────────────────────────

def _client(reg):
    app = FastAPI()
    app.include_router(reg.router)
    return TestClient(app)


def test_short_telegram_targets_endpoint(monkeypatch):
    monkeypatch.setattr(
        short_reg,
        "load_telegram_targets",
        lambda profile=None: {
            "targets": [{"id": "joriel", "chat_id": 1}],
            "default": "joriel",
        },
    )
    with _client(short_reg) as client:
        r = client.get("/telegram-targets?profile=joriel")
    assert r.status_code == 200
    assert r.json()["default"] == "joriel"


def test_short_telegram_targets_endpoint_error(monkeypatch):
    def boom(profile=None):
        raise RuntimeError("no config")

    monkeypatch.setattr(short_reg, "load_telegram_targets", boom)
    with _client(short_reg) as client:
        r = client.get("/telegram-targets?profile=joriel")
    assert r.status_code == 502
    assert "no config" in r.json()["detail"]


def test_short_telegram_discover_endpoint(monkeypatch):
    called = {}

    async def discover(profile=None, timeout=60.0):
        called["profile"] = profile
        return {"status": "success"}

    monkeypatch.setattr(short_reg, "discover_telegram_targets", discover)
    monkeypatch.setattr(
        short_reg,
        "load_telegram_targets",
        lambda profile=None: {"targets": [], "default": ""},
    )
    with _client(short_reg) as client:
        r = client.post("/telegram-targets/discover?profile=joriel")
    assert r.status_code == 200
    assert called.get("profile") == "joriel"


def test_short_config_roundtrips_telegram_keys(monkeypatch):
    pub: dict = {}

    def load():
        return dict(pub)

    def save(cfg):
        pub.clear()
        pub.update(cfg)

    monkeypatch.setattr(short_reg, "_load_publish_cfg", load)
    monkeypatch.setattr(short_reg, "_save_publish_cfg", save)
    with _client(short_reg) as client:
        r = client.post(
            "/config?profile=joriel",
            json={
                "short_telegram_alert_enabled": True,
                "telegram_alert_target": "technostik",
                "short_telegram_alert_template": "  <b>{title}</b>\n{url}  ",
            },
        )
        assert r.status_code == 200
        cfg = client.get("/config?profile=joriel").json()
    assert pub["telegram_alert_target"] == "technostik"
    assert pub["short_telegram_alert_template"] == "<b>{title}</b>\n{url}"
    assert cfg["short_telegram_alert_enabled"] is True
    assert cfg["telegram_alert_target"] == "technostik"
    assert cfg["short_telegram_alert_template"] == "<b>{title}</b>\n{url}"


def test_long_config_roundtrips_telegram_keys(monkeypatch):
    pub: dict = {}

    def load():
        return dict(pub)

    def save(cfg):
        pub.clear()
        pub.update(cfg)

    monkeypatch.setattr(long_reg, "_load_publish_cfg", load)
    monkeypatch.setattr(long_reg, "_save_publish_cfg", save)
    with _client(long_reg) as client:
        r = client.post(
            "/config?profile=joriel",
            json={
                "long_telegram_alert_enabled": True,
                "telegram_alert_target": "joriel",
                "long_telegram_alert_template": "Nouvelle vidéo : {title} {url}",
            },
        )
        assert r.status_code == 200
        cfg = client.get("/config?profile=joriel").json()
    assert pub["telegram_alert_target"] == "joriel"
    assert pub["long_telegram_alert_template"] == "Nouvelle vidéo : {title} {url}"
    assert cfg["long_telegram_alert_enabled"] is True
    assert cfg["telegram_alert_target"] == "joriel"
    assert cfg["long_telegram_alert_template"] == "Nouvelle vidéo : {title} {url}"
