from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plugins.youtube.plugin import YouTubePlugin
from plugins.rss.plugin import RSSPlugin


class TestYouTubePlugin:
    def test_validate_identifier_channel_id(self):
        plugin = YouTubePlugin({}, {"identifier": "UC123456789"})
        assert plugin.validate_identifier("UC123456789") is True

    def test_validate_identifier_handle(self):
        plugin = YouTubePlugin({}, {"identifier": "UC123456789"})
        assert plugin.validate_identifier("@somechannel") is True

    def test_validate_identifier_channel_url(self):
        plugin = YouTubePlugin({}, {"identifier": "https://www.youtube.com/channel/UC123456789"})
        assert plugin.validate_identifier("https://www.youtube.com/channel/UC123456789") is True

    def test_validate_identifier_invalid(self):
        plugin = YouTubePlugin({}, {"identifier": "UC123456789"})
        assert plugin.validate_identifier("invalid") is False
        assert plugin.validate_identifier("http://example.com") is False

    def test_resolve_channel_id_direct(self):
        plugin = YouTubePlugin({}, {"identifier": "UC123456789"})
        assert plugin._resolve_channel_id("UC123456789") == "UC123456789"

    def test_resolve_channel_id_url(self):
        plugin = YouTubePlugin({}, {"identifier": "https://www.youtube.com/channel/UC123456789"})
        assert (
            plugin._resolve_channel_id("https://www.youtube.com/channel/UC123456789")
            == "UC123456789"
        )

    def test_resolve_channel_id_handle_not_implemented(self):
        plugin = YouTubePlugin({}, {"identifier": "UC123456789"})
        with pytest.raises(NotImplementedError):
            plugin._resolve_channel_id("@somechannel")

    def test_get_identifier_display(self):
        plugin = YouTubePlugin({}, {"identifier": "UC123456789"})
        assert plugin.get_identifier_display("UC123456789") == "UC123456789"


class TestRSSPlugin:
    def test_validate_identifier_valid_url(self):
        plugin = RSSPlugin({}, {"identifier": "https://example.com/feed.xml"})
        assert plugin.validate_identifier("https://example.com/feed.xml") is True

    def test_validate_identifier_rss_in_url(self):
        plugin = RSSPlugin({}, {"identifier": "https://example.com/rss"})
        assert plugin.validate_identifier("https://example.com/rss") is True

    def test_validate_identifier_feed_in_url(self):
        plugin = RSSPlugin({}, {"identifier": "https://example.com/feed"})
        assert plugin.validate_identifier("https://example.com/feed") is True

    def test_validate_identifier_atom_in_url(self):
        plugin = RSSPlugin({}, {"identifier": "https://example.com/atom.xml"})
        assert plugin.validate_identifier("https://example.com/atom.xml") is True

    def test_validate_identifier_invalid(self):
        plugin = RSSPlugin({}, {"identifier": "https://example.com"})
        assert plugin.validate_identifier("https://example.com") is False
        assert plugin.validate_identifier("not-a-url") is False
        assert plugin.validate_identifier("ftp://example.com") is False

    def test_get_identifier_display_fallback(self):
        plugin = RSSPlugin({}, {"identifier": "https://example.com/feed.xml"})
        assert (
            plugin.get_identifier_display("https://example.com/feed.xml")
            == "https://example.com/feed.xml"
        )
