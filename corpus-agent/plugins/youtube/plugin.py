from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import structlog

from core.models import Document
from plugins.base import ItemMeta, SourcePlugin

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Transport layer — swappable for tests
# ---------------------------------------------------------------------------

class Transport:
    def list_videos(self, channel_id: str, limit: int) -> list[dict]:
        raise NotImplementedError

    def get_transcript(self, video_id: str, cookies: str | None) -> str | None:
        raise NotImplementedError

    def download_audio(self, video_id: str, cookies: str | None) -> Path | None:
        raise NotImplementedError


@dataclass
class YouTubeTransport(Transport):
    """
    Real transport using:
      - Google API client + OAuth2 for video listing
      - youtube-transcript-api for transcripts (no auth)
      - yt-dlp + openai-whisper as audio/transcription fallback

    Required extras: pip install google-api-python-client google-auth-oauthlib
                                   youtube-transcript-api
    Optional extras: pip install yt-dlp openai-whisper
    """

    client_secret_path: str

    # ------------------------------------------------------------------
    # OAuth helpers
    # ------------------------------------------------------------------

    def _get_youtube_client(self):
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise RuntimeError(
                "google-api-python-client and google-auth-oauthlib are required: "
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

    # ------------------------------------------------------------------
    # Transport interface
    # ------------------------------------------------------------------

    def list_videos(self, channel_id: str, limit: int) -> list[dict]:
        youtube = self._get_youtube_client()

        # Resolve uploads playlist from channel id
        channel_resp = youtube.channels().list(
            part="contentDetails", id=channel_id
        ).execute()

        items = channel_resp.get("items", [])
        if not items:
            raise RuntimeError(f"Channel not found or no content: {channel_id}")

        uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        logger.info("channel_resolved", channel_id=channel_id, playlist=uploads_playlist)

        videos: list[dict] = []
        page_token = None

        while len(videos) < limit:
            batch = min(50, limit - len(videos))
            resp = youtube.playlistItems().list(
                part="snippet",
                playlistId=uploads_playlist,
                maxResults=batch,
                pageToken=page_token,
            ).execute()

            for item in resp.get("items", []):
                snippet = item["snippet"]
                video_id = snippet["resourceId"]["videoId"]
                videos.append({
                    "id": video_id,
                    "title": snippet.get("title", video_id),
                    "published_at": snippet.get("publishedAt", "1970-01-01T00:00:00Z"),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                })

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        logger.info("videos_listed", channel_id=channel_id, count=len(videos))
        return videos

    def get_transcript(self, video_id: str, cookies: str | None) -> str | None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
        except ImportError as exc:
            raise RuntimeError(
                "youtube-transcript-api is required: pip install youtube-transcript-api"
            ) from exc

        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            # prefer manually created, then auto-generated; prefer English
            try:
                transcript = transcript_list.find_manually_created_transcript(["en"])
            except Exception:
                try:
                    transcript = transcript_list.find_generated_transcript(["en"])
                except Exception:
                    transcript = next(iter(transcript_list))

            chunks = transcript.fetch()
            text = " ".join(c["text"] for c in chunks)
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
            raise RuntimeError(
                "yt-dlp is required for audio fallback: pip install yt-dlp"
            ) from exc

        out_dir = Path(tempfile.mkdtemp())
        url = f"https://www.youtube.com/watch?v={video_id}"
        out_template = str(out_dir / "%(id)s.%(ext)s")

        ydl_opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
            }],
        }
        if cookies:
            ydl_opts["cookiefile"] = cookies

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
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
# Whisper transcription (called by plugin, not transport — keeps transport lean)
# ---------------------------------------------------------------------------

def transcribe_audio(audio_path: Path, model_size: str = "base") -> str:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "openai-whisper is required for audio transcription: pip install openai-whisper"
        ) from exc

    logger.info("whisper_transcribing", path=str(audio_path), model=model_size)
    model = whisper.load_model(model_size)
    result = model.transcribe(str(audio_path))
    text = result["text"].strip()
    logger.info("whisper_done", path=str(audio_path), chars=len(text))

    # Clean up temp audio
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
            self.whisper_model: str = str(
                (config.get("whisper") or {}).get("model", "base")  # type: ignore[union-attr]
            )
            client_secret_path = str(yt_cfg.get("client_secret_path", ""))  # type: ignore[union-attr]
        except Exception as exc:
            raise ValueError("Missing youtube.channel_id in config") from exc

        self.transport = transport or YouTubeTransport(client_secret_path=client_secret_path)

    def list_items(self, limit: int, since: datetime | None = None) -> list[ItemMeta]:
        videos = self.transport.list_videos(self.channel_id, limit)
        out: list[ItemMeta] = []
        for video in videos:
            updated = datetime.fromisoformat(
                video["published_at"].replace("Z", "+00:00")
            )
            # strip timezone for naive comparison (store uses naive datetimes)
            updated = updated.replace(tzinfo=None)
            if since and updated <= since:
                continue
            out.append(ItemMeta(
                source_id=video["id"],
                updated_at=updated,
                metadata=video,
            ))
        logger.info("items_listed", source=self.name, count=len(out))
        return out

    def fetch(self, item_meta: ItemMeta) -> Document:
        video_id = item_meta.source_id
        meta = item_meta.metadata or {}

        transcript = self.transport.get_transcript(video_id, self.cookies)

        if transcript is None:
            logger.info("transcript_unavailable_trying_audio", video_id=video_id)
            audio = self.transport.download_audio(video_id, self.cookies)
            if audio is None:
                raise RuntimeError(
                    f"No transcript and audio download failed for video {video_id}"
                )
            transcript = transcribe_audio(audio, self.whisper_model)

        return Document(
            source_plugin=self.name,
            source_id=video_id,
            title=str(meta.get("title", video_id)),
            raw_text=transcript,
            updated_at=item_meta.updated_at,
            url=str(meta.get("url")) if meta.get("url") else None,
            metadata=meta,
        )
