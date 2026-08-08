from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

from googleapiclient.errors import HttpError
import pytest

from core.models import Document
from core.sync_engine import SyncEngine
from core.sync_errors import APIRateLimitError
from plugins.base import ItemMeta, SourcePlugin
from plugins.youtube.plugin import YouTubePlugin


class FakeResp:
    status = 403
    reason = "Forbidden"

    def __init__(self, retry_after: str | None = None):
        self._retry_after = retry_after

    def get(self, key, default=None):
        if key == "Retry-After":
            return self._retry_after or default
        return default


def quota_http_error(retry_after: str | None = None) -> HttpError:
    return HttpError(
        FakeResp(retry_after),
        b'{"error": {"errors": [{"reason": "quotaExceeded"}]}}',
    )


class RaisingClient:
    def __init__(self, error: Exception):
        self._error = error

    def get_all_owned_videos(self, channel_id, max_results=None, page_token=None):
        raise self._error

    def get_channel_videos(self, channel_id, max_results=None):
        raise self._error


class MockTransport:
    def get_uploads_playlist(self, channel_id: str) -> str:
        return "PLx"

    def iter_playlist_pages(self, playlist_id: str):
        yield [
            {
                "snippet": {
                    "resourceId": {"videoId": "v1"},
                    "title": "Video",
                    "publishedAt": "2024-01-01T00:00:00Z",
                }
            }
        ]

    def get_video_details(self, video_ids: list[str]) -> dict:
        return {
            vid: {
                "contentDetails": {"duration": "PT2M00S"},
                "snippet": {"description": "d", "title": "V", "publishedAt": "2024-01-01T00:00:00Z"},
                "status": {"privacyStatus": "public"},
            }
            for vid in video_ids
        }

    def get_transcript(self, video_id: str, cookies: str | None):
        return "hello"

    def download_audio(self, video_id: str, cookies: str | None):
        return None


def test_api_rate_limit_error_sets_quota_reset_at():
    before = datetime.now(timezone.utc)
    err = APIRateLimitError("quota exceeded", retry_after_seconds=3600)
    reset_at = datetime.fromisoformat(err.quota_reset_at)
    assert err.retry_after_seconds == 3600
    assert before + timedelta(seconds=3600) <= reset_at <= datetime.now(timezone.utc) + timedelta(seconds=3600)


def test_api_rate_limit_error_without_retry_after():
    err = APIRateLimitError("quota exceeded")
    assert err.retry_after_seconds is None
    assert err.quota_reset_at is None


def test_plugin_raises_api_rate_limit_error_on_quota():
    plugin = YouTubePlugin(
        {"youtube": {"channel_id": "c"}}, transport=MockTransport()
    )
    plugin._get_api_client = lambda debug=False: RaisingClient(
        quota_http_error(retry_after="3600")
    )

    with pytest.raises(APIRateLimitError) as exc_info:
        plugin.list_items(10, known_id_dates={}, scan_all=True)

    assert exc_info.value.retry_after_seconds == 3600
    assert exc_info.value.quota_reset_at is not None


def test_plugin_re_raises_non_quota_http_error():
    plugin = YouTubePlugin(
        {"youtube": {"channel_id": "c"}}, transport=MockTransport()
    )
    plugin._get_api_client = lambda debug=False: RaisingClient(
        HttpError(FakeResp(403), b'{"error": {"code": 403, "errors": [{"reason": "forbidden"}]}}')
    )

    with pytest.raises(HttpError):
        plugin.list_items(10, known_id_dates={}, scan_all=True)


class QuotaListPlugin(SourcePlugin):
    name = "youtube"

    def list_items(self, limit, known_id_dates=None, debug=False):
        raise APIRateLimitError("quota exceeded", retry_after_seconds=60)

    def fetch(self, item_meta: ItemMeta):
        return Document(
            source_plugin="youtube",
            source_id=item_meta.source_id,
            title="A",
            raw_text="text",
        )


def test_sync_engine_propagates_api_rate_limit_error(store, embedder):
    engine = SyncEngine(store, embedder)
    with pytest.raises(APIRateLimitError):
        engine.sync(QuotaListPlugin(), mode="backfill", limit=1)


def _main_with_reload():
    import cli.main as cli_mod

    importlib.reload(cli_mod)
    return cli_mod.main


def test_scan_youtube_quota_is_click_exception(runner, mock_env, monkeypatch):
    from plugins.youtube import plugin as yt_plugin

    def fake_client(self, debug=False):
        return RaisingClient(quota_http_error())

    monkeypatch.setattr(yt_plugin.YouTubePlugin, "_get_api_client", fake_client)

    main = _main_with_reload()
    result = runner.invoke(main, ["scan", "--source", "youtube"])
    assert result.exit_code != 0
    assert "quota" in result.output.lower()


def test_sync_backfill_quota_is_click_exception(runner, mock_env, monkeypatch):
    from plugins.youtube import plugin as yt_plugin

    def fake_client(self, debug=False):
        return RaisingClient(quota_http_error())

    monkeypatch.setattr(yt_plugin.YouTubePlugin, "_get_api_client", fake_client)

    main = _main_with_reload()
    result = runner.invoke(
        main, ["sync", "--source", "youtube", "--mode", "backfill", "--use-api"]
    )
    assert result.exit_code != 0
    assert "quota" in result.output.lower()
