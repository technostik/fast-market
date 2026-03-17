from __future__ import annotations

from plugins.youtube.plugin import Transport, YouTubePlugin


class MockTransport(Transport):
    def get_uploads_playlist(self, channel_id: str) -> str:
        return "PLx"

    def iter_playlist_pages(self, playlist_id: str):
        yield [{"snippet": {"resourceId": {"videoId": "v1"}, "title": "Video", "publishedAt": "2024-01-01T00:00:00Z"}}]

    def get_video_details(self, video_ids: list[str]) -> dict[str, dict]:
        return {
            "v1": {
                "contentDetails": {"duration": "PT2M00S"},
                "snippet": {"description": "desc", "title": "Video", "publishedAt": "2024-01-01T00:00:00Z"},
                "status": {"privacyStatus": "public"},
            }
        }

    def get_transcript(self, video_id: str, cookies: str | None):
        return "hello"

    def download_audio(self, video_id: str, cookies: str | None):
        return None


def test_youtube_fetch():
    plugin = YouTubePlugin({"youtube": {"channel_id": "c"}}, transport=MockTransport())
    item = plugin.list_items(1)[0]
    doc = plugin.fetch(item)
    assert "hello" in doc.raw_text
