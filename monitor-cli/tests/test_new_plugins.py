from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from plugins.channel_list.plugin import ChannelListPlugin
from plugins.json.plugin import JsonPlugin


class TestChannelListPlugin:
    """Test the channel_list source plugin."""

    def test_parse_channels_from_metadata(self):
        """Test parsing channels list from metadata."""
        plugin = ChannelListPlugin(
            {},
            {
                "id": "test_source",
                "origin": "list",
                "metadata": {
                    "channels": [
                        {"id": "UCabcdef1234567890abcdef", "title": "Channel A"},
                        {"id": "UCqrstuvwxyz1234567890ab", "title": "Channel B"},
                    ]
                },
            },
        )
        assert len(plugin.channels) == 2
        assert plugin.channels[0]["id"] == "UCabcdef1234567890abcdef"
        assert plugin.channels[0]["title"] == "Channel A"
        assert plugin.channels[1]["id"] == "UCqrstuvwxyz1234567890ab"

    def test_parse_channels_missing_metadata(self):
        """Test error when channels metadata is missing."""
        with pytest.raises(ValueError, match="requires 'channels' in metadata"):
            ChannelListPlugin(
                {},
                {"id": "test_source", "origin": "list", "metadata": {}},
            )

    def test_parse_channels_empty_list(self):
        """Test error when channels list is empty."""
        with pytest.raises(ValueError, match="requires 'channels' in metadata"):
            ChannelListPlugin(
                {},
                {"id": "test_source", "origin": "list", "metadata": {"channels": []}},
            )

    def test_parse_channels_invalid_id(self):
        """Test error when channel ID is invalid."""
        with pytest.raises(ValueError, match="Invalid channel ID"):
            ChannelListPlugin(
                {},
                {
                    "id": "test_source",
                    "origin": "list",
                    "metadata": {
                        "channels": [{"id": "invalid_id", "title": "Bad"}]
                    },
                },
            )

    def test_parse_channels_missing_id_field(self):
        """Test error when channel entry missing 'id' field."""
        with pytest.raises(ValueError, match="missing required 'id' field"):
            ChannelListPlugin(
                {},
                {
                    "id": "test_source",
                    "origin": "list",
                    "metadata": {
                        "channels": [{"title": "No ID"}]
                    },
                },
            )

    def test_parse_channels_without_title(self):
        """Test that channels without title use ID as title."""
        plugin = ChannelListPlugin(
            {},
            {
                "id": "test_source",
                "origin": "list",
                "metadata": {
                    "channels": [{"id": "UCabcdef123456ghijklmnop"}]
                },
            },
        )
        assert plugin.channels[0]["title"] == "UCabcdef123456ghijklmnop"

    def test_validate_identifier(self):
        """validate_identifier always returns True (origin is placeholder)."""
        plugin = ChannelListPlugin(
            {},
            {
                "id": "test_source",
                "origin": "list",
                "metadata": {
                    "channels": [{"id": "UCabcdef123456ghijklmnop"}]
                },
            },
        )
        assert plugin.validate_identifier("anything") is True

    def test_get_identifier_display(self):
        plugin = ChannelListPlugin(
            {},
            {
                "id": "test_source",
                "origin": "list",
                "metadata": {
                    "channels": [
                        {"id": "UCabcdef1234567890abcdef", "title": "A"},
                        {"id": "UCqrstuvwxyz1234567890ab", "title": "B"},
                    ]
                },
            },
        )
        display = plugin.get_identifier_display("list")
        assert "2 channel(s)" in display

    @pytest.mark.asyncio
    async def test_fetch_new_items_cooldown(self):
        """Test that cooldown prevents fetching."""
        from datetime import timedelta

        recent = datetime.now(timezone.utc) - timedelta(minutes=5)
        plugin = ChannelListPlugin(
            {},
            {
                "id": "test_source",
                "origin": "list",
                "metadata": {
                    "channels": [{"id": "UCabcdef123456ghijklmnop"}]
                },
                "last_check": recent.isoformat(),
                "check_interval": "15m",
            },
        )
        result = await plugin.fetch_new_items()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_new_items_delegates_to_youtube(self):
        """Test that fetch_new_items delegates to YouTubePlugin."""
        from core.models import ItemMetadata

        plugin = ChannelListPlugin(
            {},
            {
                "id": "test_source",
                "origin": "list",
                "metadata": {
                    "channels": [
                        {"id": "UCabcdef1234567890abcdef", "title": "Channel A"},
                    ]
                },
            },
        )

        mock_item = ItemMetadata(
            id="video123",
            title="Test Video",
            url="https://youtube.com/watch?v=video123",
            published_at=datetime.now(timezone.utc),
            content_type="video",
            source_plugin="youtube",
            source_id="test_source__UCabcdef1234567890abcdef",
            extra={"channel_name": "Channel A"},
        )

        with patch("plugins.youtube.plugin.YouTubePlugin") as MockYTPlugin:
            mock_yt_instance = MagicMock()

            async def mock_fetch(*args, **kwargs):
                return [mock_item]
            mock_yt_instance.fetch_new_items = mock_fetch
            MockYTPlugin.return_value = mock_yt_instance

            result = await plugin.fetch_new_items()

            # Verify source_id was overridden
            assert len(result) == 1
            assert result[0].source_id == "test_source"
            assert result[0].extra.get("channel_list_title") == "Channel A"


class TestJsonPlugin:
    """Test the json source plugin."""

    def test_requires_command_in_metadata(self):
        """Test error when command is missing from metadata."""
        with pytest.raises(ValueError, match="requires 'command' in metadata"):
            JsonPlugin(
                {},
                {"id": "test_source", "origin": "api", "metadata": {}},
            )

    def test_validate_identifier(self):
        """validate_identifier always returns True (origin is placeholder)."""
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "echo '[]'"}},
        )
        assert plugin.validate_identifier("anything") is True

    def test_get_identifier_display(self):
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "curl -s https://api.example.com/items"}},
        )
        display = plugin.get_identifier_display("api")
        assert "cmd:" in display

    def test_parse_published_iso(self):
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "echo '[]'"}},
        )
        dt = plugin._parse_published("2024-01-15T10:30:00Z")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15

    def test_parse_published_unix_timestamp(self):
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "echo '[]'"}},
        )
        dt = plugin._parse_published(1705312200)
        assert dt.year == 2024

    def test_parse_published_none(self):
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "echo '[]'"}},
        )
        dt = plugin._parse_published(None)
        assert dt is not None  # Should return current time

    def test_normalize_content_type_valid(self):
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "echo '[]'"}},
        )
        assert plugin._normalize_content_type("video") == "video"
        assert plugin._normalize_content_type("short") == "short"
        assert plugin._normalize_content_type("article") == "article"
        assert plugin._normalize_content_type("medium_video") == "medium_video"
        assert plugin._normalize_content_type("long_video") == "long_video"

    def test_normalize_content_type_invalid(self):
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "echo '[]'"}},
        )
        assert plugin._normalize_content_type("podcast") == "article"
        assert plugin._normalize_content_type(None) == "article"
        assert plugin._normalize_content_type("") == "article"

    @pytest.mark.asyncio
    async def test_fetch_new_items_cooldown(self):
        """Test that cooldown prevents fetching."""
        from datetime import timedelta

        recent = datetime.now(timezone.utc) - timedelta(minutes=5)
        plugin = JsonPlugin(
            {},
            {
                "id": "test_source",
                "origin": "api",
                "metadata": {"command": "echo '[]'"},
                "last_check": recent.isoformat(),
                "check_interval": "15m",
            },
        )
        result = await plugin.fetch_new_items()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_new_items_from_command(self):
        """Test fetching items from a command output."""
        now = datetime.now(timezone.utc).isoformat()
        command = f'echo \'[{{"item_id": "item1", "item_title": "Test Item", "item_url": "https://example.com/1", "item_content_type": "article", "item_published": "{now}"}}]\''

        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": command}},
        )
        result = await plugin.fetch_new_items()

        assert len(result) == 1
        assert result[0].id == "item1"
        assert result[0].title == "Test Item"
        assert result[0].url == "https://example.com/1"
        assert result[0].content_type == "article"

    @pytest.mark.asyncio
    async def test_fetch_new_items_command_failure(self):
        """Test handling of command failure."""
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "exit 1"}},
        )
        result = await plugin.fetch_new_items()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_new_items_invalid_json(self):
        """Test handling of invalid JSON output."""
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "echo 'not json'"}},
        )
        result = await plugin.fetch_new_items()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_new_items_single_object(self):
        """Test that a single JSON object is wrapped in a list."""
        now = datetime.now(timezone.utc).isoformat()
        command = f'echo \'{{"item_id": "single", "item_title": "Single Item", "item_url": "https://example.com/single", "item_content_type": "video", "item_published": "{now}"}}\''

        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": command}},
        )
        result = await plugin.fetch_new_items()

        assert len(result) == 1
        assert result[0].id == "single"

    @pytest.mark.asyncio
    async def test_fetch_new_items_extra_fields(self):
        """Test that extra fields are captured in item.extra."""
        now = datetime.now(timezone.utc).isoformat()
        command = f'echo \'[{{"item_id": "item1", "item_title": "Test", "item_url": "https://example.com", "item_content_type": "article", "item_published": "{now}", "views": 100, "author": "John"}}]\''

        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": command}},
        )
        result = await plugin.fetch_new_items()

        assert result[0].extra.get("views") == 100
        assert result[0].extra.get("author") == "John"

    @pytest.mark.asyncio
    async def test_fetch_new_items_empty_output(self):
        """Test handling of empty command output."""
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "echo ''"}},
        )
        result = await plugin.fetch_new_items()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_new_items_missing_item_id(self):
        """Test that items without item_id are skipped."""
        plugin = JsonPlugin(
            {},
            {"id": "test_source", "origin": "api", "metadata": {"command": "echo '[{\"item_title\": \"No ID\"}]'"}},
        )
        result = await plugin.fetch_new_items()
        assert result == []
