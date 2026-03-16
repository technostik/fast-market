from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import structlog

from core.models import Document
from plugins.base import ItemMeta, SourcePlugin

logger = structlog.get_logger(__name__)


class Transport:
    def list_videos(self, channel_id: str, limit: int) -> list[dict]:
        raise NotImplementedError

    def get_transcript(self, video_id: str, cookies: str | None) -> str | None:
        raise NotImplementedError

    def download_audio(self, video_id: str, cookies: str | None) -> Path | None:
        raise NotImplementedError


@dataclass
class YouTubeTransport(Transport):
    def list_videos(self, channel_id: str, limit: int) -> list[dict]:
        raise RuntimeError("YouTubeTransport is not implemented in this scaffold")

    def get_transcript(self, video_id: str, cookies: str | None) -> str | None:
        return None

    def download_audio(self, video_id: str, cookies: str | None) -> Path | None:
        return None


class YouTubePlugin(SourcePlugin):
    name = "youtube"

    def __init__(self, config: dict[str, object], transport: Transport | None = None) -> None:
        try:
            yt_cfg = config["youtube"]  # type: ignore[index]
            self.channel_id = str(yt_cfg["channel_id"])
            self.cookies = yt_cfg.get("cookies")  # type: ignore[union-attr]
        except Exception as exc:
            raise ValueError("Missing youtube.channel_id in config") from exc
        self.transport = transport or YouTubeTransport()

    def list_items(self, limit: int, since: datetime | None = None) -> list[ItemMeta]:
        videos = self.transport.list_videos(self.channel_id, limit)
        out: list[ItemMeta] = []
        for video in videos:
            updated = datetime.fromisoformat(video["published_at"])
            if since and updated <= since:
                continue
            out.append(ItemMeta(source_id=video["id"], updated_at=updated, metadata=video))
        return out

    def fetch(self, item_meta: ItemMeta) -> Document:
        transcript = self.transport.get_transcript(item_meta.source_id, self.cookies)
        if transcript is None:
            audio = self.transport.download_audio(item_meta.source_id, self.cookies)
            if audio is None:
                raise RuntimeError("Transcript and audio are unavailable")
            transcript = f"Audio fallback placeholder for {audio.name}"
        meta = item_meta.metadata or {}
        return Document(
            source_plugin=self.name,
            source_id=item_meta.source_id,
            title=str(meta.get("title", item_meta.source_id)),
            raw_text=transcript,
            updated_at=item_meta.updated_at,
            url=str(meta.get("url", "")) or None,
            metadata=meta,
        )
