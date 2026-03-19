from __future__ import annotations

import re
from datetime import datetime, timezone

import feedparser

from plugins.base import SourcePlugin, ItemMetadata


class YouTubePlugin(SourcePlugin):
    name = "youtube"

    def __init__(self, config: dict, source_config: dict):
        super().__init__(config, source_config)
        self.channel_id = self._resolve_channel_id(source_config["identifier"])

    def _resolve_channel_id(self, identifier: str) -> str:
        if identifier.startswith("UC"):
            return identifier
        elif "@" in identifier:
            raise NotImplementedError(
                "YouTube handle resolution requires API key. "
                "Use channel ID directly or set up YouTube API."
            )
        else:
            match = re.search(r"channel/(UC[a-zA-Z0-9_-]+)", identifier)
            if match:
                return match.group(1)
        raise ValueError(f"Invalid YouTube identifier: {identifier}")

    async def fetch_new_items(
        self, last_item_id: str | None = None, limit: int = 50
    ) -> list[ItemMetadata]:
        rss_url = (
            f"https://www.youtube.com/feeds/videos.xml?channel_id={self.channel_id}"
        )
        feed = feedparser.parse(rss_url)

        items = []
        for entry in feed.entries[:limit]:
            duration = 0
            is_short = False
            if hasattr(entry, "media_content") and entry.media_content:
                duration = int(entry.media_content[0].get("duration", 0))
                is_short = duration < 60

            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime.fromtimestamp(
                    entry.published_parsed.timestamp(), tz=timezone.utc
                )
            else:
                published = datetime.now(timezone.utc)

            vid_id = getattr(entry, "yt_videoid", None) or getattr(
                entry, "id", entry.link
            )

            item = ItemMetadata(
                id=vid_id,
                title=entry.title,
                url=entry.link,
                published_at=published,
                content_type="short" if is_short else "video",
                source_plugin=self.name,
                source_identifier=self.channel_id,
                raw=entry.__dict__,
                extra={
                    "duration_seconds": duration,
                    "is_short": is_short,
                    "channel_id": self.channel_id,
                    "channel_name": getattr(feed.feed, "title", "") or "",
                    "views": 0,
                    "likes": 0,
                },
            )

            if last_item_id and item.id == last_item_id:
                break

            items.append(item)

        return items

    def validate_identifier(self, identifier: str) -> bool:
        return bool(
            identifier.startswith("UC")
            or "@" in identifier
            or "youtube.com/channel/" in identifier
        )

    def get_identifier_display(self, identifier: str) -> str:
        return identifier
