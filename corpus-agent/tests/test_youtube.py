from __future__ import annotations

from pathlib import Path

from plugins.youtube.plugin import Transport, YouTubePlugin


class MockTransport(Transport):
    def list_videos(self, channel_id: str, limit: int):
        return [{"id": "v1", "published_at": "2024-01-01T00:00:00", "title": "Video"}]

    def get_transcript(self, video_id: str, cookies: str | None):
        return "hello"

    def download_audio(self, video_id: str, cookies: str | None) -> Path | None:
        return None


def test_youtube_fetch():
    plugin = YouTubePlugin({"youtube": {"channel_id": "c"}}, transport=MockTransport())
    item = plugin.list_items(1)[0]
    doc = plugin.fetch(item)
    assert doc.raw_text == "hello"
