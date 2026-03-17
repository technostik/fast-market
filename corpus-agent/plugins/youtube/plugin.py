from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

import structlog

from core.models import Document
from plugins.base import ItemMeta, SourcePlugin

logger = structlog.get_logger(__name__)

# Privacy statuses considered publicly accessible.
_PUBLIC_STATUSES = {"public"}


def _parse_iso8601_duration(duration: str) -> int:
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not match:
        return 0
    h, m, s = (int(x or 0) for x in match.groups())
    return h * 3600 + m * 60 + s


def _format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


# ---------------------------------------------------------------------------
# Transport abstraction (injectable for tests)
# ---------------------------------------------------------------------------

class Transport:
    def get_uploads_playlist(self, channel_id: str) -> str:
        """Return the uploads playlist ID for the channel. Raises on failure."""
        raise NotImplementedError

    def iter_playlist_pages(self, playlist_id: str) -> Iterator[list[dict]]:
        """Yield raw playlist pages, each a list of playlistItem snippet dicts."""
        raise NotImplementedError

    def get_video_details(self, video_ids: list[str]) -> dict[str, dict]:
        """Return video_id -> full video resource (contentDetails+snippet+status)."""
        raise NotImplementedError

    def get_transcript(self, video_id: str, cookies: str | None) -> str | None:
        raise NotImplementedError

    def download_audio(self, video_id: str, cookies: str | None) -> Path | None:
        raise NotImplementedError


@dataclass
class YouTubeTransport(Transport):
    client_secret_path: str

    def _get_client(self):
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise RuntimeError(
                "pip install google-api-python-client google-auth-oauthlib"
            ) from exc

        token_path = Path(self.client_secret_path).parent / "token.json"
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path))
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secret_path,
                    scopes=["https://www.googleapis.com/auth/youtube.readonly"],
                )
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json(), encoding="utf-8")
            logger.info("oauth_token_saved", path=str(token_path))
        return build("youtube", "v3", credentials=creds)

    def get_uploads_playlist(self, channel_id: str) -> str:
        youtube = self._get_client()
        resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
        items = resp.get("items", [])
        if not items:
            raise RuntimeError(f"Channel not found or no content: {channel_id}")
        playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        logger.info("channel_resolved", channel_id=channel_id, playlist=playlist_id)
        return playlist_id

    def iter_playlist_pages(self, playlist_id: str) -> Iterator[list[dict]]:
        youtube = self._get_client()
        page_token = None
        while True:
            resp = youtube.playlistItems().list(
                part="snippet", playlistId=playlist_id,
                maxResults=50, pageToken=page_token,
            ).execute()
            page = resp.get("items", [])
            if not page:
                return
            yield page
            page_token = resp.get("nextPageToken")
            if not page_token:
                return

    def get_video_details(self, video_ids: list[str]) -> dict[str, dict]:
        youtube = self._get_client()
        out: dict[str, dict] = {}
        for i in range(0, len(video_ids), 50):
            resp = youtube.videos().list(
                part="contentDetails,snippet,status",
                id=",".join(video_ids[i:i + 50]),
            ).execute()
            for v in resp.get("items", []):
                out[v["id"]] = v
        return out

    def get_transcript(self, video_id: str, cookies: str | None) -> str | None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
        except ImportError as exc:
            raise RuntimeError("pip install youtube-transcript-api") from exc

        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
            transcript = transcript_list.find_transcript(["en", "fr"])
            fetched = transcript.fetch()
            text = " ".join(entry["text"] for entry in fetched.to_raw_data())
            logger.info("transcript_fetched", video_id=video_id, chars=len(text))
            return text
        except (NoTranscriptFound, TranscriptsDisabled) as exc:
            logger.info("no_transcript", video_id=video_id, reason=str(exc))
            return None
        except Exception as exc:
            logger.error("transcript_error", video_id=video_id, error=str(exc))
            return None

    def download_audio(self, video_id: str, cookies: str | None) -> Path | None:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("pip install yt-dlp") from exc

        out_dir = Path(tempfile.mkdtemp())
        ydl_opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        }
        if cookies:
            ydl_opts["cookiefile"] = cookies

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        except Exception as exc:
            logger.error("audio_download_failed", video_id=video_id, error=str(exc))
            return None

        mp3_files = list(out_dir.glob("*.mp3"))
        if not mp3_files:
            logger.error("audio_file_missing", video_id=video_id, dir=str(out_dir))
            return None

        logger.info("audio_downloaded", video_id=video_id, path=str(mp3_files[0]))
        return mp3_files[0]


# ---------------------------------------------------------------------------
# Whisper fallback
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class YouTubePlugin(SourcePlugin):
    name = "youtube"

    def __init__(self, config: dict[str, object], transport: Transport | None = None) -> None:
        try:
            yt_cfg = config["youtube"]  # type: ignore[index]
            self.channel_id = str(yt_cfg["channel_id"])  # type: ignore[index]
            self.cookies: str | None = yt_cfg.get("cookies")  # type: ignore[union-attr]
            self.whisper_model: str = str((config.get("whisper") or {}).get("model", "base"))  # type: ignore[union-attr]
            client_secret_path = str(yt_cfg.get("client_secret_path", ""))  # type: ignore[union-attr]
            # When False (default), non-public videos are skipped during sync.
            # Set youtube.index_non_public: true in config.yaml to override.
            # privacy_status is always stored on the document regardless.
            self.index_non_public: bool = bool(yt_cfg.get("index_non_public", False))  # type: ignore[union-attr]
        except Exception as exc:
            raise ValueError("Missing youtube.channel_id in config") from exc

        self.transport = transport or YouTubeTransport(client_secret_path=client_secret_path)

    def list_items(
        self,
        limit: int,
        known_id_dates: dict[str, datetime | None] | None = None,
    ) -> list[ItemMeta]:
        """Walk the uploads playlist newest-first, returning up to `limit` unindexed videos.

        Uses ID-based dedup via known_id_dates — date values are ignored for YouTube.
        Date cursors break after the first sync because every backlog video has
        published_at older than the newest indexed one, causing the entire backlog to
        be silently skipped. Pages through the API until `limit` new eligible videos
        are found or the channel is exhausted.
        """
        known = set(known_id_dates or {})
        out: list[ItemMeta] = []
        skipped_privacy = 0

        playlist_id = self.transport.get_uploads_playlist(self.channel_id)

        for page in self.transport.iter_playlist_pages(playlist_id):
            if len(out) >= limit:
                break

            # Enrich the whole page in one API call
            video_ids = [item["snippet"]["resourceId"]["videoId"] for item in page]
            details = self.transport.get_video_details(video_ids)

            for item in page:
                if len(out) >= limit:
                    break

                snippet = item["snippet"]
                video_id = snippet["resourceId"]["videoId"]

                if video_id in known:
                    continue  # already indexed — keep paging for older unindexed ones

                detail = details.get(video_id, {})
                privacy = detail.get("status", {}).get("privacyStatus", "unknown")

                if not self.index_non_public and privacy not in _PUBLIC_STATUSES:
                    logger.info("video_skipped_privacy", video_id=video_id, privacy_status=privacy)
                    skipped_privacy += 1
                    continue

                duration = _parse_iso8601_duration(
                    detail.get("contentDetails", {}).get("duration", "")
                )
                description = detail.get("snippet", {}).get("description", "")
                published_at = snippet.get("publishedAt", "1970-01-01T00:00:00Z")
                updated = datetime.fromisoformat(published_at.replace("Z", "+00:00")).replace(tzinfo=None)

                logger.info(
                    "video_listed",
                    video_id=video_id,
                    title=snippet.get("title", ""),
                    duration=_format_duration(duration),
                    privacy_status=privacy,
                )
                out.append(ItemMeta(
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
                ))

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
                raise RuntimeError(f"No transcript and audio download failed for video {video_id}")
            transcript = transcribe_audio(audio, self.whisper_model)

        raw_text = f"{description}\n\n{transcript}".strip() if description else transcript

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
