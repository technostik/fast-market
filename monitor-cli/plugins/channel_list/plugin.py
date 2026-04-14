from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from plugins.base import SourcePlugin, ItemMetadata


class ChannelListPlugin(SourcePlugin):
    """Monitor a list of YouTube channels defined in metadata or external YAML file.

    Metadata (legacy):
        channels: List of {"id": "UC...", "title": "Channel Name"} dicts

    External file (new):
        file: Path to YAML channel list file (uses common youtube channel list format)
        thematic: Name of thematic to use from the file
    """

    name = "channel_list"

    def __init__(self, config: dict, source_config: dict):
        super().__init__(config, source_config)
        self.source_id = source_config.get("id", "")
        self.use_external_file = "file" in self.metadata or "thematic" in self.metadata

        if self.use_external_file:
            self.channels: list[dict[str, str]] = self._load_from_external_file()
        else:
            self.channels: list[dict[str, str]] = self._parse_channels()

    def _load_from_external_file(self) -> list[dict[str, str]]:
        """Load channels from external YAML channel list file."""
        from common.core.config import load_youtube_config
        from common.core.paths import get_youtube_channel_list_path
        from common.youtube.channel_list import load_channel_list_file

        # Get file path from metadata or use default
        file_path = self.metadata.get("file")
        if file_path:
            path = Path(file_path).expanduser()
        else:
            # Check youtube config for channel_list_path
            yt_cfg = load_youtube_config()
            path = Path(
                yt_cfg.get("channel_list_path", str(get_youtube_channel_list_path()))
            ).expanduser()

        if not path.exists():
            raise ValueError(f"Channel list file not found: {path}")

        # Load the channel list file
        channel_list = load_channel_list_file(path)

        # Get thematic name from metadata
        thematic_name = self.metadata.get("thematic")
        if not thematic_name:
            raise ValueError(
                "When using external file, you must specify 'thematic' in metadata. "
                "Example: metadata: {file: /path/to/channels.yaml, thematic: tech}"
            )

        # Get channels from the specified thematic
        thematic = channel_list.get_thematic(thematic_name)
        if thematic is None:
            raise ValueError(
                f"Thematic '{thematic_name}' not found in {path}. "
                f"Available: {', '.join(channel_list.list_thematic_names()) or 'none'}"
            )

        channels = []
        for ch_name in thematic.channels:
            # Resolve channel entry from global list
            ch_entry = channel_list.get_channel_by_name(ch_name)
            if ch_entry is None:
                continue  # Skip if channel was removed from global list

            channels.append(
                {
                    "id": ch_entry.id,
                    "title": ch_entry.title,
                    "name": ch_entry.name,
                }
            )

        if not channels:
            raise ValueError(f"No channels in thematic '{thematic_name}'")

        return channels

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
                raise ValueError("metadata.channels must be a list of {id, title} objects")

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
        seen_item_ids: set[str] | None = None,
    ) -> list[ItemMetadata]:
        """Fetch new videos from all channels in the list.

        This plugin delegates to the YouTube plugin for each channel,
        then merges and sorts results by published date.

        Each channel maintains its own last_item_id in source metadata
        to properly track fetch progress per channel.

        Args:
            seen_item_ids: Only call yt-dlp for details on items NOT in this set.

        Returns:
            List of ItemMetadata. Total RSS raw count is stored in
            self._rss_raw_count.
        """
        self._rss_raw_count = 0
        if not self._should_fetch(force):
            return []

        # Import YouTubePlugin dynamically to reuse its fetch logic
        from plugins.youtube.plugin import YouTubePlugin

        per_channel_limit = max(1, limit // len(self.channels)) if self.channels else limit
        all_items: list[ItemMetadata] = []

        # Get per-channel last_item_ids from metadata
        channel_last_ids: dict[str, str] = self.metadata.get("last_item_ids_by_channel", {})

        print(f"  → channel_list: {len(self.channels)} channels, {per_channel_limit} videos each")

        for i, channel in enumerate(self.channels):
            channel_id = channel["id"]
            # Use channel-specific last_item_id instead of the source-level one
            channel_last_id = channel_last_ids.get(channel_id)

            # Create a temporary YouTube plugin instance for this channel
            yt_source_config = {
                "id": f"{self.source_id}__{channel_id}",
                "origin": channel_id,
                "metadata": {},
                "last_check": self.last_check,
                "slowdown": self.slowdown,
            }
            yt_plugin = YouTubePlugin(self.config, yt_source_config)

            try:
                items = await yt_plugin.fetch_new_items(
                    last_item_id=channel_last_id,
                    limit=per_channel_limit,
                    force=force,
                    seen_item_ids=seen_item_ids,
                )
                # rss_raw is the total we asked for, not what was actually returned
                self._rss_raw_count += per_channel_limit
                if channel_last_id:
                    print(
                        f"    [{i + 1}/{len(self.channels)}] channel={channel['title'][:20]} returned={len(items)} (last_id={channel_last_id[:12]}...)"
                    )
                else:
                    print(
                        f"    [{i + 1}/{len(self.channels)}] channel={channel['title'][:20]} returned={len(items)} (no last_id)"
                    )
                # Override source_id and add channel metadata to items
                for item in items:
                    item.source_id = self.source_id
                    # Set SOURCE_URL placeholder to YouTube channel URL
                    item.extra["channel_url"] = f"https://www.youtube.com/channel/{channel_id}"
                    # Set SOURCE_DESC placeholder to channel name
                    item.extra["channel_name"] = channel["title"]
                    item.extra["channel_list_title"] = channel["title"]
                all_items.extend(items)

                # Update channel's last_item_id if we fetched new items
                if items:
                    newest_item = max(items, key=lambda x: x.published_at)
                    channel_last_ids[channel_id] = newest_item.id
            except Exception as e:
                print(f"⚠️ Failed to fetch channel {channel_id}: {e}")

        # Save updated per-channel last_item_ids back to metadata
        if channel_last_ids:
            self.metadata["last_item_ids_by_channel"] = channel_last_ids

        # Sort by published date, newest first
        all_items.sort(key=lambda x: x.published_at, reverse=True)

        # Apply limit
        all_items = all_items[:limit]

        return all_items

    async def close(self):
        pass
