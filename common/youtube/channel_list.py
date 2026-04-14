from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from common.core.yaml_utils import dump_yaml


class ChannelEntry(BaseModel):
    """A single channel entry in the channel list."""

    name: str
    """Display name for the channel."""

    title: str = ""
    """Channel title (from YouTube API)."""

    id: str
    """YouTube channel ID (UC...)."""

    subscribers: int = 0
    """Subscriber count (if known)."""

    date_added: str = ""
    """ISO 8601 date when channel was added to the list."""

    metadata: dict = {}
    """Additional metadata (e.g., last_fetch for hot commands)."""

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "ChannelEntry":
        return cls(**data)


class ThematicList(BaseModel):
    """A thematic list - a named group of channels."""

    name: str
    """Name of the thematic list (e.g., 'tech', 'ai', 'gaming')."""

    channels: list[str] = Field(default_factory=list)
    """List of channel names in this thematic."""

    def get_channel_names(self) -> list[str]:
        """Get all channel names in this thematic."""
        return self.channels

    def has_channel(self, channel_name: str) -> bool:
        """Check if a channel name is in this thematic."""
        return channel_name in self.channels

    def add_channel(self, channel_name: str) -> None:
        """Add a channel name to the thematic list."""
        if channel_name not in self.channels:
            self.channels.append(channel_name)

    def remove_channel(self, channel_name: str) -> bool:
        """Remove a channel name from the thematic list."""
        if channel_name in self.channels:
            self.channels.remove(channel_name)
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "channels": self.channels,
        }


class ChannelListFile(BaseModel):
    """
    YAML channel list file structure.

    This file format is used to store a collection of YouTube channels
    organized into thematic groups. Both monitor and youtube hot commands
    can read from this file.

    File structure:
        channels:
          - name: "Channel Display Name"
            title: "Channel Title"
            id: "UCxxxxxxxxxxxxxxxxxxxx1"
            subscribers: 1000000
            date_added: "2024-01-01T00:00:00Z"
          - ...
        thematics:
          - name: "tech"
            channels:
              - name: "..."
                id: "..."
                ...
          - name: "ai"
            channels:
              - ...
    """

    channels: list[ChannelEntry] = Field(default_factory=list)
    """Flat list of all known channels."""

    thematics: list[ThematicList] = Field(default_factory=list)
    """Thematic groups of channels."""

    def get_thematic(self, name: str) -> Optional[ThematicList]:
        """Get a thematic by name."""
        for t in self.thematics:
            if t.name == name:
                return t
        return None

    def add_thematic(self, thematic: ThematicList) -> None:
        """Add or replace a thematic."""
        self.thematics = [t for t in self.thematics if t.name != thematic.name]
        self.thematics.append(thematic)

    def remove_thematic(self, name: str) -> bool:
        """Remove a thematic."""
        before = len(self.thematics)
        self.thematics = [t for t in self.thematics if t.name != name]
        return len(self.thematics) < before

    def list_thematic_names(self) -> list[str]:
        """Get all thematic names."""
        return [t.name for t in self.thematics]

    def add_channel_to_thematic(
        self, channel_name: str, thematic_name: str
    ) -> None:
        """Add a channel name to a specific thematic (creates thematic if needed)."""
        thematic = self.get_thematic(thematic_name)
        if thematic is None:
            thematic = ThematicList(name=thematic_name)
            self.add_thematic(thematic)
        thematic.add_channel(channel_name)

    def remove_channel_from_thematic(
        self, channel_name: str, thematic_name: str
    ) -> bool:
        """Remove a channel name from a thematic."""
        thematic = self.get_thematic(thematic_name)
        if thematic is None:
            return False
        return thematic.remove_channel(channel_name)

    def get_channel_names_for_thematic(self, thematic_name: str) -> list[str]:
        """Get all channel names in a thematic."""
        thematic = self.get_thematic(thematic_name)
        if thematic is None:
            return []
        return thematic.channels

    def get_channel_by_name(self, channel_name: str) -> Optional[ChannelEntry]:
        """Get a channel from the global list by name."""
        for ch in self.channels:
            if ch.name == channel_name:
                return ch
        return None

    def to_dict(self) -> dict:
        return {
            "channels": [ch.to_dict() for ch in self.channels],
            "thematics": [t.to_dict() for t in self.thematics],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChannelListFile":
        channels = [
            ChannelEntry(**ch) for ch in data.get("channels", [])
        ]
        thematics = [
            ThematicList(
                name=t["name"],
                channels=t.get("channels", []),
            )
            for t in data.get("thematics", [])
        ]
        return cls(channels=channels, thematics=thematics)


# ─── File I/O helpers ────────────────────────────────────────────────────────


def load_channel_list_file(path: Path) -> ChannelListFile:
    """Load a channel list YAML file.

    Returns empty ChannelListFile if file doesn't exist.
    """
    if not path.exists():
        return ChannelListFile()

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

    if data is None:
        return ChannelListFile()

    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML mapping, got {type(data).__name__}")

    return ChannelListFile.from_dict(data)


def save_channel_list_file(path: Path, channel_list: ChannelListFile) -> None:
    """Save a channel list to a YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dump_yaml(channel_list.to_dict(), sort_keys=False),
        encoding="utf-8",
    )


def create_channel_entry(
    channel_id: str,
    name: str,
    title: str = "",
    subscribers: int = 0,
) -> ChannelEntry:
    """Create a new channel entry with current date."""
    return ChannelEntry(
        name=name,
        title=title,
        id=channel_id,
        subscribers=subscribers,
        date_added=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
