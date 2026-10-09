"""Tests for `video generate` (fal.ai cloud text/image-to-video). Network-free."""

import json
import sys
from pathlib import Path

import click
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.generate import fal as fal_mod
from commands.generate import models as models_mod
from commands.generate.register import register


def _make_cmd():
    return register({}).click_command


def test_resolve_auto_text_and_image():
    text_eps = models_mod.resolve_candidate_endpoints("auto", False)
    image_eps = models_mod.resolve_candidate_endpoints("auto", True)
    assert len(text_eps) == len(models_mod.MODEL_CATALOG) == len(image_eps)
    assert all("text-to-video" in e for e in text_eps)
    assert all("image-to-video" in e for e in image_eps)
    assert text_eps[0] == models_mod.MODEL_CATALOG[0].text_endpoint


def _endpoint(alias: str) -> str:
    return next(m for m in models_mod.MODEL_CATALOG if m.alias == alias).text_endpoint


def test_resolve_alias_and_custom():
    assert models_mod.resolve_candidate_endpoints("kling", False) == [
        _endpoint("kling")
    ]
    assert models_mod.resolve_candidate_endpoints(
        "fal-ai/veo3.1", False
    ) == ["fal-ai/veo3.1"]
    try:
        models_mod.resolve_candidate_endpoints("nope", False)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown model")


def test_build_payload_and_set_parsing():
    payload = models_mod.build_payload(
        "a cat",
        duration=5,
        seed=7,
        extra=models_mod.parse_set_option(("guidance=3.5", "audio=true", "name=hi=x")),
    )
    assert payload == {
        "prompt": "a cat",
        "duration": 5,
        "seed": 7,
        "guidance": 3.5,
        "audio": True,
        "name": "hi=x",
    }
    try:
        models_mod.parse_set_option(("oops-no-equals",))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for bad --set")


def test_is_quota_error():
    assert fal_mod.is_quota_error(fal_mod.FalError("insufficient balance", status=402))
    assert fal_mod.is_quota_error(fal_mod.FalError("too many requests", status=429))
    assert fal_mod.is_quota_error(fal_mod.FalError("quota exceeded"))
    assert not fal_mod.is_quota_error(fal_mod.FalError("rejected key", status=401))
    assert not fal_mod.is_quota_error(fal_mod.FalError("boom", status=500))


def test_extract_video_url_variants():
    assert fal_mod.extract_video_url({"video": {"url": "http://v/x.mp4"}}) == "http://v/x.mp4"
    assert fal_mod.extract_video_url({"video": "http://v/y.mp4"}) == "http://v/y.mp4"
    assert fal_mod.extract_video_url({"videos": [{"url": "http://v/z.mp4"}]}) == "http://v/z.mp4"
    assert fal_mod.extract_video_url({"video_url": "http://v/w.mp4"}) == "http://v/w.mp4"
    try:
        fal_mod.extract_video_url({"nothing": 1})
    except fal_mod.FalError:
        pass
    else:
        raise AssertionError("expected FalError for missing url")


def test_resolve_api_key_prefers_explicit_and_env(monkeypatch):
    assert fal_mod.resolve_api_key("k123") == "k123"
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("FAL_API_KEY", raising=False)
    monkeypatch.setenv("FAL_API_KEY", "from-env")
    assert fal_mod.resolve_api_key(None) == "from-env"
    monkeypatch.setenv("FAL_KEY", "from-fal-key")
    assert fal_mod.resolve_api_key(None) == "from-fal-key"


def test_generate_auto_falls_back_on_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "dummy")
    calls = []

    def fake_generate_video(*, endpoint, payload, output_path, api_key, timeout, progress_cb=None):
        calls.append(endpoint)
        if len(calls) == 1:
            raise fal_mod.FalError("insufficient balance", status=402)
        Path(output_path).write_bytes(b"fake-video")
        return {"request_id": "r2", "video_url": "http://cdn/v.mp4", "result": {}}

    monkeypatch.setattr(fal_mod, "generate_video", fake_generate_video)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(_make_cmd(), ["a sunset over mountains"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 2
    assert "Using model:" in result.stderr or "Using model:" in result.output


def test_generate_creates_missing_parents(tmp_path, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "dummy")

    def fake_generate_video(*, endpoint, payload, output_path, api_key, timeout, progress_cb=None):
        Path(output_path).write_bytes(b"fake-video")
        return {"request_id": "r1", "video_url": "http://cdn/v.mp4", "result": {}}

    monkeypatch.setattr(fal_mod, "generate_video", fake_generate_video)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            _make_cmd(),
            ["hello world", "-o", "deep/nested/out.mp4", "--format", "json"],
        )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output.strip().splitlines()[-1])
    assert data["path"].endswith("deep/nested/out.mp4")
    assert data["model"] == models_mod.MODEL_CATALOG[0].text_endpoint
    assert Path(data["path"]).exists()


def test_generate_image_to_video_uses_image_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "dummy")
    seen = {}

    def fake_upload(path, key):
        seen["uploaded"] = path
        return "http://cdn/img.png"

    def fake_generate_video(*, endpoint, payload, output_path, api_key, timeout, progress_cb=None):
        seen["endpoint"] = endpoint
        seen["payload"] = payload
        Path(output_path).write_bytes(b"fake-video")
        return {"request_id": "r1", "video_url": "http://cdn/v.mp4", "result": {}}

    monkeypatch.setattr(fal_mod, "upload_image", fake_upload)
    monkeypatch.setattr(fal_mod, "generate_video", fake_generate_video)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("frame.png").write_bytes(b"\x89PNG fake")
        result = runner.invoke(_make_cmd(), ["animate this", "--image", "frame.png"])
    assert result.exit_code == 0, result.output
    assert seen["endpoint"] == models_mod.MODEL_CATALOG[0].image_endpoint
    assert seen["payload"]["image_url"] == "http://cdn/img.png"


def test_image_and_image_url_conflict():
    runner = CliRunner()
    result = runner.invoke(
        _make_cmd(),
        ["x", "--image", __file__, "--image-url", "http://x/y.png"],
    )
    assert result.exit_code != 0


def test_free_models_only_sandbox_free():
    free = models_mod.free_models()
    assert {m.alias for m in free} == {"minimax", "flux"}
    assert all(m.sandbox_free for m in free)


def test_free_only_flag_lists_curated_free():
    runner = CliRunner()
    result = runner.invoke(_make_cmd(), ["--list-models", "--free-only"])
    assert result.exit_code == 0, result.output
    assert "minimax/h3-max/text-to-video" in result.output
    assert "flux-3/text-to-video/draft" in result.output
    assert "kling" not in result.output


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


def test_submit_uses_server_urls_and_poll_threads_them(tmp_path, monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(("POST", url))
        return _FakeResp({
            "request_id": "r-1",
            # Gateway canonicalizes the app route: returned URLs differ
            # from {endpoint}/requests/{id}/... (hand-built ones 405).
            "status_url": "https://queue.fal.run/fal-ai/minimax/requests/r-1/status",
            "response_url": "https://queue.fal.run/fal-ai/minimax/requests/r-1",
        })

    statuses = iter([{"status": "IN_QUEUE", "queue_position": 2}, {"status": "COMPLETED"}])

    def fake_get(url, **kwargs):
        calls.append(("GET", url))
        if url.endswith("/status"):
            return _FakeResp(next(statuses))
        return _FakeResp({"video": {"url": "http://cdn/v.mp4"}})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)

    handle = fal_mod.submit("minimax/h3-max/text-to-video", {"prompt": "x"}, "k")
    assert handle["status_url"].endswith("/fal-ai/minimax/requests/r-1/status")
    result = fal_mod.poll_result(
        handle["status_url"], handle["response_url"], "k", poll_interval=0
    )
    assert result == {"video": {"url": "http://cdn/v.mp4"}}
    get_urls = [u for m, u in calls if m == "GET"]
    assert get_urls[0] == handle["status_url"]
    assert get_urls[-1] == handle["response_url"]
    # No hand-built .../h3-max/text-to-video/requests/... path was ever hit.
    assert not any("h3-max/text-to-video/requests" in u for _, u in calls)


def test_poll_completed_with_error_raises(tmp_path, monkeypatch):
    def fake_get(url, **kwargs):
        return _FakeResp({"status": "COMPLETED", "error": "balance too low", "error_type": "billing"})

    import requests

    monkeypatch.setattr(requests, "get", fake_get)
    try:
        fal_mod.poll_result("http://s/status", "http://s/resp", "k", poll_interval=0)
    except fal_mod.FalError as exc:
        assert "balance too low" in str(exc)
    else:
        raise AssertionError("expected FalError for COMPLETED-with-error")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
