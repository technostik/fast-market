import sys
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Add monitor-cli to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "monitor-cli"))

from plugins.youtube.plugin import YouTubePlugin


@pytest.mark.asyncio
async def test_rss_vs_yt_dlp_video_comparison():
    """Test that RSS and yt-dlp fetch return comparable video lists and dates."""

    channel_id = "UCXuqSBlHAE6Xw-yeJA0Tunw"  # Linus Tech Tips
    config = {}
    source_config = {"id": "test-source", "origin": channel_id}

    plugin = YouTubePlugin(config, source_config)

    # Mock yt-dlp data (same videos, same order)
    yt_dlp_entries = [
        {
            "id": "video1",
            "title": "Test Video 1",
            "upload_date": "20240115",
            "duration": 600,
            "url": "https://youtube.com/watch?v=video1",
            "view_count": 1000,
            "like_count": 100,
            "comment_count": 50,
        },
        {
            "id": "video2",
            "title": "Test Video 2",
            "upload_date": "20240114",
            "duration": 300,
            "url": "https://youtube.com/watch?v=video2",
            "view_count": 500,
            "like_count": 50,
            "comment_count": 25,
        },
    ]

    # Mock network calls
    with (
        patch("requests.head") as mock_head,
        patch("feedparser.parse") as mock_feedparser,
        patch(
            "plugins.youtube.plugin.YouTubePlugin._get_video_details_async"
        ) as mock_details,
        patch("yt_dlp.YoutubeDL") as mock_ydl_class,
    ):
        # Mock RSS availability check
        mock_head.return_value.status_code = 200

        # Mock RSS feed data
        rss_entries = [
            {
                "yt_videoid": "video1",
                "title": "Test Video 1",
                "published_parsed": (2024, 1, 15, 10, 0, 0, 0, 15, 0),
                "media_content": [{"duration": "600"}],
                "link": "https://youtube.com/watch?v=video1",
            },
            {
                "yt_videoid": "video2",
                "title": "Test Video 2",
                "published_parsed": (2024, 1, 14, 10, 0, 0, 0, 14, 0),
                "media_content": [{"duration": "300"}],
                "link": "https://youtube.com/watch?v=video2",
            },
        ]
        mock_feedparser.return_value = MagicMock(
            feed=MagicMock(title="Test Channel"),
            entries=rss_entries,
            bozo_exception=None,
        )

        # Mock yt-dlp
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.extract_info.return_value = {
            "entries": yt_dlp_entries,
            "channel": "Test Channel",
        }
        mock_ydl_class.return_value = mock_ydl_instance

        # Mock detailed fetch (for RSS path) - return appropriate data for each video
        async def mock_details_func(video_id):
            if video_id == "video1":
                return {
                    "duration_seconds": 600,
                    "views": 1000,
                    "likes": 100,
                    "comments": 50,
                    "upload_date": datetime(2024, 1, 15, tzinfo=timezone.utc),
                    "is_short": False,
                    "channel_id": channel_id,
                    "channel_name": "Test Channel",
                }
            elif video_id == "video2":
                return {
                    "duration_seconds": 300,
                    "views": 500,
                    "likes": 50,
                    "comments": 25,
                    "upload_date": datetime(2024, 1, 14, tzinfo=timezone.utc),
                    "is_short": False,
                    "channel_id": channel_id,
                    "channel_name": "Test Channel",
                }
            return {}

        mock_details.side_effect = mock_details_func
        # Mock RSS availability check
        mock_head.return_value.status_code = 200

        # Mock RSS feed data
        rss_entries = [
            {
                "yt_videoid": "video1",
                "title": "Test Video 1",
                "published_parsed": (2024, 1, 15, 10, 0, 0, 0, 15, 0),
                "media_content": [{"duration": "600"}],
                "link": "https://youtube.com/watch?v=video1",
            },
            {
                "yt_videoid": "video2",
                "title": "Test Video 2",
                "published_parsed": (2024, 1, 14, 10, 0, 0, 0, 14, 0),
                "media_content": [{"duration": "300"}],
                "link": "https://youtube.com/watch?v=video2",
            },
        ]
        mock_feedparser.return_value = MagicMock(
            feed=MagicMock(title="Test Channel"),
            entries=rss_entries,
            bozo_exception=None,
        )

        # Mock yt-dlp data (same videos, same order)
        yt_dlp_entries = [
            {
                "id": "video1",
                "title": "Test Video 1",
                "upload_date": "20240115",
                "duration": 600,
                "url": "https://youtube.com/watch?v=video1",
                "view_count": 1000,
                "like_count": 100,
                "comment_count": 50,
            },
            {
                "id": "video2",
                "title": "Test Video 2",
                "upload_date": "20240114",
                "duration": 300,
                "url": "https://youtube.com/watch?v=video2",
                "view_count": 500,
                "like_count": 50,
                "comment_count": 25,
            },
        ]

        # Mock detailed fetch (for RSS path) - return appropriate data for each video
        async def mock_details_func(video_id):
            if video_id == "video1":
                return {
                    "duration_seconds": 600,
                    "views": 1000,
                    "likes": 100,
                    "comments": 50,
                    "upload_date": datetime(2024, 1, 15, tzinfo=timezone.utc),
                    "is_short": False,
                    "channel_id": channel_id,
                    "channel_name": "Test Channel",
                }
            elif video_id == "video2":
                return {
                    "duration_seconds": 300,
                    "views": 500,
                    "likes": 50,
                    "comments": 25,
                    "upload_date": datetime(2024, 1, 14, tzinfo=timezone.utc),
                    "is_short": False,
                    "channel_id": channel_id,
                    "channel_name": "Test Channel",
                }
            return {}

        mock_details.side_effect = mock_details_func

        # Fetch via RSS (normal path)
        rss_items = await plugin.fetch_new_items(limit=10)

        # Fetch via yt-dlp fallback (force RSS failure)
        with patch.object(plugin, "_check_rss_availability", return_value=False):
            with patch.object(plugin, "_should_fetch_with_slowdown", return_value=True):
                yt_dlp_items = await plugin._fetch_via_yt_dlp(limit=10)

        # Compare results
        assert len(rss_items) == len(yt_dlp_items), (
            f"RSS ({len(rss_items)}) and yt-dlp ({len(yt_dlp_items)}) should return same number of items"
        )

        # Sort both lists by video ID for comparison
        rss_sorted = sorted(rss_items, key=lambda x: x.id)
        yt_dlp_sorted = sorted(yt_dlp_items, key=lambda x: x.id)

        for rss_item, yt_dlp_item in zip(rss_sorted, yt_dlp_sorted):
            # Compare basic attributes
            assert rss_item.id == yt_dlp_item.id, (
                f"Video IDs should match: {rss_item.id} vs {yt_dlp_item.id}"
            )
            assert rss_item.title == yt_dlp_item.title, (
                f"Titles should match for {rss_item.id}"
            )
            assert rss_item.url == yt_dlp_item.url, (
                f"URLs should match for {rss_item.id}"
            )

            # Compare dates (should be within reasonable tolerance)
            date_diff = abs(
                (rss_item.published_at - yt_dlp_item.published_at).total_seconds()
            )
            assert date_diff < 86400, (
                f"Dates should be close for {rss_item.id}: RSS={rss_item.published_at}, yt-dlp={yt_dlp_item.published_at}"
            )

            # Compare content type
            assert rss_item.content_type == yt_dlp_item.content_type, (
                f"Content types should match for {rss_item.id}: {rss_item.content_type}"
            )

            # Compare source info
            assert rss_item.source_plugin == yt_dlp_item.source_plugin, (
                "Source plugin should be 'youtube' for both"
            )
            assert rss_item.source_id == yt_dlp_item.source_id, "Source ID should match"
