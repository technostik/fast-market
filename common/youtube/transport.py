from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import feedparser

from common import structlog

logger = structlog.get_logger(__name__)


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


class Transport:
    def get_uploads_playlist(self, channel_id: str) -> str:
        raise NotImplementedError

    def iter_playlist_pages(self, playlist_id: str) -> Iterator[list[dict]]:
        raise NotImplementedError

    def get_video_details(self, video_ids: list[str]) -> dict[str, dict]:
        raise NotImplementedError

    def get_transcript(self, video_id: str, cookies: str | None) -> str | None:
        raise NotImplementedError

    def download_audio(self, video_id: str, cookies: str | None) -> Path | None:
        raise NotImplementedError


class RSSPlaylistTransport(Transport):
    def __init__(self, cookies: str | None = None):
        self.cookies = cookies

    def get_uploads_playlist(self, channel_id: str) -> str:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    def iter_playlist_pages(self, playlist_id: str) -> Iterator[list[dict]]:
        feed = feedparser.parse(playlist_id)
        if hasattr(feed, "bozo_exception") and feed.bozo_exception:
            logger.warning(
                "rss_parse_error", feed_url=playlist_id, error=str(feed.bozo_exception)
            )
            return

        page: list[dict] = []
        for entry in feed.entries:
            video_id = None
            if hasattr(entry, "yt_videoid"):
                video_id = entry.yt_videoid
            elif hasattr(entry, "id") and "video:" in entry.id:
                video_id = entry.id.split("video:")[-1]
            elif hasattr(entry, "link"):
                match = re.search(r"v=([a-zA-Z0-9_-]+)", entry.link)
                if match:
                    video_id = match.group(1)

            if not video_id:
                continue

            published = datetime.now(timezone.utc)
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime.fromtimestamp(
                        time.mktime(entry.published_parsed), tz=timezone.utc
                    )
                except (OverflowError, ValueError, TypeError):
                    pass

            duration = 0
            if hasattr(entry, "media_content") and entry.media_content:
                try:
                    duration = int(entry.media_content[0].get("duration", 0))
                except (ValueError, TypeError):
                    pass

            video_url = f"https://youtube.com/watch?v={video_id}"
            if hasattr(entry, "link") and entry.link:
                if "watch?v=" in entry.link:
                    video_url = entry.link

            page.append(
                {
                    "snippet": {
                        "resourceId": {"videoId": video_id},
                        "title": entry.get("title", "Untitled"),
                        "description": entry.get("summary", "")[:500],
                        "publishedAt": published.isoformat(),
                    },
                    "video_url": video_url,
                    "duration": duration,
                }
            )

        if page:
            yield page

    def get_video_details(self, video_ids: list[str]) -> dict[str, dict]:
        if not video_ids:
            return {}

        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("pip install yt-dlp") from exc

        out: dict[str, dict] = {}

        ydl_opts: dict = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "ignoreerrors": True,
            "no_color": True,
        }
        if self.cookies:
            ydl_opts["cookiefile"] = self.cookies

        for video_id in video_ids:
            url = f"https://www.youtube.com/watch?v={video_id}"
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        upload_date = None
                        if info.get("upload_date"):
                            try:
                                upload_date = datetime.strptime(
                                    info["upload_date"], "%Y%m%d"
                                ).replace(tzinfo=timezone.utc)
                            except ValueError:
                                pass

                        out[video_id] = {
                            "id": video_id,
                            "contentDetails": {
                                "duration": info.get("duration", 0),
                            },
                            "snippet": {
                                "title": info.get("title", ""),
                                "description": info.get("description", "")[:500],
                            },
                            "status": {
                                "privacyStatus": info.get("availability", "public"),
                            },
                            "_custom": {
                                "upload_date": upload_date,
                                "duration_seconds": info.get("duration", 0),
                            },
                        }
            except Exception as exc:
                logger.warning("yt_dlp_fetch_error", video_id=video_id, error=str(exc))
                continue

        return out

    def get_transcript(self, video_id: str, cookies: str | None) -> str | None:
        try:
            from youtube_transcript_api import (
                YouTubeTranscriptApi,
                NoTranscriptFound,
                TranscriptsDisabled,
            )
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
        except OSError:
            raise
        except Exception as exc:
            if "rate" in str(exc).lower() or "429" in str(exc):
                raise
            raise

    def download_audio(self, video_id: str, cookies: str | None) -> Path | None:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("pip install yt-dlp") from exc

        import tempfile

        out_dir = Path(tempfile.mkdtemp())
        ydl_opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        }
        use_cookies = cookies or self.cookies
        if use_cookies:
            ydl_opts["cookiefile"] = use_cookies

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
