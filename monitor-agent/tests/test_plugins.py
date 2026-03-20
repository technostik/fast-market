from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from plugins.rss.plugin import RSSPlugin
from plugins.youtube.plugin import YouTubePlugin
from plugins.yt_search.plugin import YouTubeSearchPlugin


class TestSourcePluginCooldown:
    """Test cooldown functionality in base SourcePlugin class."""

    def test_default_check_interval(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin.check_interval == "15m"

    def test_default_check_interval_rss(self):
        plugin = RSSPlugin({}, {"identifier": "https://example.com/feed.xml"})
        assert plugin.check_interval == "15m"

    def test_default_check_interval_yt_search(self):
        plugin = YouTubeSearchPlugin({}, {"identifier": "python tutorial"})
        assert plugin.check_interval == "15m"

    def test_parse_interval_seconds(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin._parse_interval("30s") == 30

    def test_parse_interval_minutes(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin._parse_interval("15m") == 900

    def test_parse_interval_hours(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin._parse_interval("1h") == 3600

    def test_parse_interval_days(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin._parse_interval("2d") == 172800

    def test_parse_interval_invalid_defaults(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin._parse_interval("invalid") == 900
        assert plugin._parse_interval("") == 900

    def test_parse_interval_with_custom_interval_arg(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin._parse_interval("30m") == 1800
        assert plugin._parse_interval("2h") == 7200

    def test_should_fetch_no_last_check(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin._should_fetch() is True

    def test_should_fetch_with_last_check_none_string(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop", "last_check": None})
        assert plugin._should_fetch() is True

    def test_should_fetch_with_last_check_recent(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=5)
        plugin = YouTubePlugin(
            {},
            {
                "identifier": "UCabcdef123456ghijklmnop",
                "last_check": recent.isoformat(),
                "metadata": {"check_interval": "15m"},
            },
        )
        assert plugin._should_fetch() is False

    def test_should_fetch_with_last_check_old(self):
        old = datetime.now(timezone.utc) - timedelta(minutes=20)
        plugin = YouTubePlugin(
            {},
            {
                "identifier": "UCabcdef123456ghijklmnop",
                "last_check": old.isoformat(),
                "metadata": {"check_interval": "15m"},
            },
        )
        assert plugin._should_fetch() is True

    def test_should_fetch_with_custom_interval(self):
        old = datetime.now(timezone.utc) - timedelta(minutes=5)
        plugin = YouTubePlugin(
            {},
            {
                "identifier": "UCabcdef123456ghijklmnop",
                "last_check": old.isoformat(),
                "metadata": {"check_interval": "1h"},
            },
        )
        assert plugin._should_fetch() is False

    def test_should_fetch_with_datetime_object(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=5)
        plugin = YouTubePlugin(
            {},
            {
                "identifier": "UCabcdef123456ghijklmnop",
                "last_check": recent,
                "metadata": {"check_interval": "15m"},
            },
        )
        assert plugin._should_fetch() is False

    def test_should_fetch_with_invalid_date_string(self):
        plugin = YouTubePlugin(
            {},
            {
                "identifier": "UCabcdef123456ghijklmnop",
                "last_check": "not-a-date",
            },
        )
        assert plugin._should_fetch() is True

    def test_metadata_access(self):
        plugin = YouTubePlugin(
            {},
            {
                "identifier": "UCabcdef123456ghijklmnop",
                "metadata": {"theme": "tech", "priority": "high"},
            },
        )
        assert plugin.metadata["theme"] == "tech"
        assert plugin.metadata["priority"] == "high"


class TestYouTubePlugin:
    def test_validate_identifier_channel_id(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin.validate_identifier("UCabcdef123456ghijklmnop") is True

    def test_validate_identifier_handle(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin.validate_identifier("@somechannel") is True

    def test_validate_identifier_channel_url(self):
        plugin = YouTubePlugin(
            {}, {"identifier": "https://www.youtube.com/channel/UCabcdef123456ghijklmnop"}
        )
        assert (
            plugin.validate_identifier("https://www.youtube.com/channel/UCabcdef123456ghijklmnop")
            is True
        )

    def test_validate_identifier_invalid(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin.validate_identifier("invalid") is False
        assert plugin.validate_identifier("http://example.com") is False

    def test_resolve_channel_id_direct(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert plugin._resolve_channel_id("UCabcdef123456ghijklmnop") == "UCabcdef123456ghijklmnop"

    def test_resolve_channel_id_url(self):
        plugin = YouTubePlugin(
            {}, {"identifier": "https://www.youtube.com/channel/UCabcdef123456ghijklmnop"}
        )
        assert (
            plugin._resolve_channel_id("https://www.youtube.com/channel/UCabcdef123456ghijklmnop")
            == "UCabcdef123456ghijklmnop"
        )

    def test_resolve_channel_id_handle_not_implemented(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        with pytest.raises(NotImplementedError):
            plugin._resolve_channel_id("@somechannel")

    def test_get_identifier_display(self):
        plugin = YouTubePlugin({}, {"identifier": "UCabcdef123456ghijklmnop"})
        assert "UCabcdef123456ghijklmnop" in plugin.get_identifier_display(
            "UCabcdef123456ghijklmnop"
        )


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


class TestYouTubeSearchPlugin:
    def test_validate_identifier_valid(self):
        plugin = YouTubeSearchPlugin({}, {"identifier": "python tutorial"})
        assert plugin.validate_identifier("python tutorial") is True

    def test_validate_identifier_advanced(self):
        plugin = YouTubeSearchPlugin({}, {"identifier": "AI tutorial -shorts | ML"})
        assert plugin.validate_identifier("AI tutorial -shorts | ML") is True

    def test_validate_identifier_phrase(self):
        plugin = YouTubeSearchPlugin({}, {"identifier": "machine learning"})
        assert plugin.validate_identifier('"machine learning" basics') is True

    def test_validate_identifier_empty(self):
        plugin = YouTubeSearchPlugin({}, {"identifier": "python tutorial"})
        assert plugin.validate_identifier("") is False
        assert plugin.validate_identifier("   ") is False

    def test_validate_identifier_too_long(self):
        plugin = YouTubeSearchPlugin({}, {"identifier": "python tutorial"})
        long_keywords = " ".join(["word"] * 200)
        assert plugin.validate_identifier(long_keywords) is False

    def test_validate_identifier_dangerous(self):
        plugin = YouTubeSearchPlugin({}, {"identifier": "python tutorial"})
        assert plugin.validate_identifier("rm -rf /") is False
        assert plugin.validate_identifier("sudo rm") is False

    def test_get_identifier_display(self):
        plugin = YouTubeSearchPlugin({}, {"identifier": "python tutorial"})
        display = plugin.get_identifier_display("python tutorial")
        assert "python tutorial" in display
        assert display.startswith("Search:")

    def test_get_identifier_display_long(self):
        plugin = YouTubeSearchPlugin({}, {"identifier": "python tutorial"})
        long_keywords = " ".join(["word"] * 20)
        display = plugin.get_identifier_display(long_keywords)
        assert "..." in display

    def test_default_metadata(self):
        plugin = YouTubeSearchPlugin({}, {"identifier": "python tutorial"})
        assert plugin.min_views == 1000
        assert plugin.max_results == 50
        assert plugin.check_interval == "15m"

    def test_custom_metadata(self):
        plugin = YouTubeSearchPlugin(
            {},
            {
                "identifier": "python tutorial",
                "metadata": {
                    "min_views": "5000",
                    "max_results": "30",
                    "check_interval": "1h",
                },
            },
        )
        assert plugin.min_views == 5000
        assert plugin.max_results == 30
        assert plugin.check_interval == "1h"
