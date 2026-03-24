from __future__ import annotations

from datetime import datetime
from pathlib import Path

from common import structlog
from common.youtube.transport import RSSPlaylistTransport, Transport

from core.models import Document
from core.sync_errors import NetworkError, TranscriptUnavailableError
from plugins.base import ItemMeta, SourcePlugin

logger = structlog.get_logger(__name__)

_PUBLIC_STATUSES = {"public"}


def _format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


class YouTubePlugin(SourcePlugin):
    name = "youtube"

    def __init__(
        self, config: dict[str, object], transport: Transport | None = None
    ) -> None:
        try:
            yt_cfg = config["youtube"]
            self.channel_id = str(yt_cfg["channel_id"])
            self.cookies: str | None = yt_cfg.get("cookies")
            self.whisper_model: str = str(
                (config.get("whisper") or {}).get("model", "base")
            )
            self.index_non_public: bool = bool(yt_cfg.get("index_non_public", False))
        except Exception as exc:
            raise ValueError("Missing youtube.channel_id in config") from exc

        self.transport = transport or RSSPlaylistTransport(cookies=self.cookies)

    def list_items(
        self,
        limit: int,
        known_id_dates: dict[str, datetime | None] | None = None,
    ) -> list[ItemMeta]:
        known = set(known_id_dates or {})
        out: list[ItemMeta] = []
        skipped_privacy = 0

        playlist_id = self.transport.get_uploads_playlist(self.channel_id)

        for page in self.transport.iter_playlist_pages(playlist_id):
            if len(out) >= limit:
                break

            video_ids = [item["snippet"]["resourceId"]["videoId"] for item in page]
            details = self.transport.get_video_details(video_ids)

            for item in page:
                if len(out) >= limit:
                    break

                snippet = item["snippet"]
                video_id = snippet["resourceId"]["videoId"]

                if video_id in known:
                    continue

                detail = details.get(video_id, {})
                custom = detail.get("_custom", {})
                privacy = detail.get("status", {}).get("privacyStatus", "unknown")

                if not self.index_non_public and privacy not in _PUBLIC_STATUSES:
                    logger.info(
                        "video_skipped_privacy",
                        video_id=video_id,
                        privacy_status=privacy,
                    )
                    skipped_privacy += 1
                    continue

                duration = custom.get("duration_seconds") or detail.get(
                    "contentDetails", {}
                ).get("duration", 0)
                if isinstance(duration, str):
                    import re

                    match = re.match(
                        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or ""
                    )
                    if match:
                        h, m, s = (int(x or 0) for x in match.groups())
                        duration = h * 3600 + m * 60 + s
                    else:
                        duration = 0

                description = detail.get("snippet", {}).get("description", "")
                published_at = snippet.get("publishedAt", "1970-01-01T00:00:00Z")

                try:
                    updated = datetime.fromisoformat(
                        published_at.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    updated = datetime.now()

                logger.info(
                    "video_listed",
                    video_id=video_id,
                    title=snippet.get("title", ""),
                    duration=_format_duration(duration),
                    privacy_status=privacy,
                )
                out.append(
                    ItemMeta(
                        source_id=video_id,
                        updated_at=updated,
                        metadata={
                            "id": video_id,
                            "title": snippet.get("title", video_id),
                            "description": description,
                            "published_at": published_at,
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "duration_seconds": duration,
                            "privacy_status": privacy,
                        },
                    )
                )

        if skipped_privacy:
            logger.info("videos_skipped_non_public", count=skipped_privacy)
        logger.info("items_listed", source=self.name, count=len(out))
        return out

    def fetch(self, item_meta: ItemMeta) -> Document:
        video_id = item_meta.source_id
        meta = item_meta.metadata or {}
        title = str(meta.get("title", video_id))
        duration = int(meta.get("duration_seconds", 0))
        description = str(meta.get("description", ""))
        privacy_status = str(meta.get("privacy_status", "unknown"))

        logger.info(
            "fetching_video",
            video_id=video_id,
            title=title,
            duration=_format_duration(duration),
            privacy_status=privacy_status,
        )

        transcript = self.transport.get_transcript(video_id, self.cookies)
        if transcript is None:
            logger.info("transcript_unavailable_trying_audio", video_id=video_id)
            audio = self.transport.download_audio(video_id, self.cookies)
            if audio is None:
                raise TranscriptUnavailableError(f"No transcript for {video_id}")
            try:
                transcript = transcribe_audio(audio, self.whisper_model)
            except OSError as exc:
                raise NetworkError(
                    f"Network error while transcribing {video_id}"
                ) from exc

        raw_text = (
            f"{description}\n\n{transcript}".strip() if description else transcript
        )

        return Document(
            source_plugin=self.name,
            source_id=video_id,
            title=title,
            raw_text=raw_text,
            updated_at=item_meta.updated_at,
            url=str(meta.get("url")) if meta.get("url") else None,
            duration_seconds=duration or None,
            privacy_status=privacy_status,
            metadata=meta,
        )


def transcribe_audio(audio_path: Path, model_size: str = "base") -> str:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError("pip install openai-whisper") from exc

    logger.info("whisper_transcribing", path=str(audio_path), model=model_size)
    model = whisper.load_model(model_size)
    result = model.transcribe(str(audio_path))
    text = result["text"].strip()
    logger.info("whisper_done", path=str(audio_path), chars=len(text))
    try:
        audio_path.unlink()
        audio_path.parent.rmdir()
    except Exception:
        pass
    return text
