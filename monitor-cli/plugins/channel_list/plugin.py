from __future__ import annotations

import re
from typing import Any

from plugins.base import SourcePlugin, ItemMetadata


class ChannelListPlugin(SourcePlugin):
    """Monitor a list of YouTube channels defined in metadata.

    Metadata:
        channels: List of {"id": "UC...", "title": "Channel Name"} dicts
    """

    name = "channel_list"

    def __init__(self, config: dict, source_config: dict):
        super().__init__(config, source_config)
        self.source_id = source_config.get("id", "")
        self.channels: list[dict[str, str]] = self._parse_channels()

    def _parse_channels(self) -> list[dict[str, str]]:
        """Parse the channels list from metadata.

        Expected format in metadata["channels"]:
            - id: "UCxxxxxxxxxxxxxxxxxxxx"  (required, channel ID)
              title: "Channel Name"         (optional, display name)
        """
        raw = self.metadata.get("channels")
        if not raw:
            raise ValueError(
                "channel_list plugin requires 'channels' in metadata. "
                "Format: [{id: 'UC...', title: 'Name'}, ...]"
            )

        if isinstance(raw, str):
            # Try to parse as YAML-like string
            import yaml

            try:
                raw = yaml.safe_load(raw)
            except Exception:
                raise ValueError(
                    "metadata.channels must be a list of {id, title} objects"
                )

        if not isinstance(raw, list):
            raise ValueError("metadata.channels must be a list")

        channels = []
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict):
                raise ValueError(f"channels[{i}] must be a dict with 'id' and optional 'title'")
            if "id" not in entry or not entry.get("id"):
                raise ValueError(f"channels[{i}] missing required 'id' field")
            channel_id = entry["id"].strip()
            if not channel_id.startswith("UC") or len(channel_id) != 24:
                raise ValueError(
                    f"channels[{i}]: Invalid channel ID '{channel_id}'. "
                    "Must be a YouTube channel ID starting with 'UC' and 24 chars."
                )
            channels.append(
                {
                    "id": channel_id,
                    "title": entry.get("title", channel_id),
                }
            )

        return channels

    def validate_identifier(self, identifier: str) -> bool:
        """For channel_list, the origin is a placeholder; validation is on metadata."""
        # origin is not used for channel_list, so accept anything
        return True

    def get_identifier_display(self, identifier: str) -> str:
        return f"{len(self.channels)} channel(s)"

    async def fetch_new_items(
        self,
        last_item_id: str | None = None,
        limit: int = 50,
        last_fetched_at: Any | None = None,
        force: bool = False,
    ) -> list[ItemMetadata]:
        """Fetch new videos from all channels in the list.

        This plugin delegates to the YouTube plugin for each channel,
        then merges and sorts results by published date.
        """
        if not self._should_fetch(force):
            return []

        # Import YouTubePlugin dynamically to reuse its fetch logic
        from plugins.youtube.plugin import YouTubePlugin

        per_channel_limit = max(1, limit // len(self.channels)) if self.channels else limit
        all_items: list[ItemMetadata] = []

        for channel in self.channels:
            # Create a temporary YouTube plugin instance for this channel
            yt_source_config = {
                "id": f"{self.source_id}__{channel['id']}",
                "origin": channel["id"],
                "metadata": {},
                "last_check": self.last_check,
                "check_interval": self.check_interval,
            }
            yt_plugin = YouTubePlugin(self.config, yt_source_config)

            try:
                items = await yt_plugin.fetch_new_items(
                    last_item_id=last_item_id,
                    limit=per_channel_limit,
                    force=force,
                )
                # Override source_id to the channel_list source so tracking works correctly
                for item in items:
                    item.source_id = self.source_id
                    item.extra["channel_list_title"] = channel["title"]
                all_items.extend(items)
            except Exception as e:
                print(f"⚠️ Failed to fetch channel {channel['id']}: {e}")

        # Sort by published date, newest first
        all_items.sort(key=lambda x: x.published_at, reverse=True)

        # Apply limit
        all_items = all_items[:limit]

        return all_items

    async def close(self):
        pass
