from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import feedparser

from common import structlog
from core.sync_errors import TranscriptUnavailableError, VideoBlockedError

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
        transcript = None
        methods_tried = []

        # Method 1: yt-dlp (try first - most reliable)
        methods_tried.append("yt-dlp")
        logger.info("trying_transcript_ytdlp", video_id=video_id)
        try:
            transcript = self._get_transcript_ytdlp(video_id, cookies)
            if transcript:
                logger.info("transcript_fetched_ytdlp", video_id=video_id)
                return transcript
        except Exception as e:
            logger.warning("transcript_ytdlp_failed", video_id=video_id, error=str(e))

        # Method 2: youtube-transcript-api (fallback)
        methods_tried.append("youtube-transcript-api")
        logger.info("trying_transcript_youtube_api", video_id=video_id)
        try:
            transcript = self._get_transcript_youtube_api(video_id)
            if transcript:
                logger.info("transcript_fetched_youtube_api", video_id=video_id)
                return transcript
        except Exception as e:
            logger.warning(
                "transcript_youtube_api_failed", video_id=video_id, error=str(e)
            )

        # Method 3: YouTube Data API v3 (final fallback)
        methods_tried.append("youtube-api-v3")
        logger.info("trying_transcript_api_v3", video_id=video_id)
        try:
            transcript = self._get_transcript_api_v3(video_id)
            if transcript:
                logger.info("transcript_fetched_api_v3", video_id=video_id)
                return transcript
        except Exception as e:
            logger.warning("transcript_api_v3_failed", video_id=video_id, error=str(e))

        if not transcript:
            logger.info(
                "no_transcript_any_method",
                video_id=video_id,
                methods_tried=methods_tried,
            )
        return transcript

    def _get_transcript_youtube_api(self, video_id: str) -> str | None:
        from youtube_transcript_api import (
            YouTubeTranscriptApi,
            NoTranscriptFound,
            TranscriptsDisabled,
        )

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
            error_msg = str(exc).lower()
            if "rate" in error_msg or "429" in error_msg:
                raise
            if "members" in error_msg or "join this channel" in error_msg:
                logger.info("video_members_only", video_id=video_id)
                raise TranscriptUnavailableError(
                    f"Video {video_id} requires channel membership"
                ) from exc
            if "blocking" in error_msg or "ip" in error_msg or "blocked" in error_msg:
                logger.info("video_blocked", video_id=video_id, reason=str(exc)[:100])
                raise VideoBlockedError(
                    f"Video {video_id} blocked by YouTube (IP blocked)"
                ) from exc
            raise

    def _get_transcript_ytdlp(self, video_id: str, cookies: str | None) -> str | None:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("pip install yt-dlp") from exc

        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts: dict = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlelangs": ["en", "fr"],
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        use_cookies = cookies or self.cookies
        if use_cookies:
            ydl_opts["cookiefile"] = use_cookies

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None

                subtitles = (
                    info.get("subtitles") or info.get("automatic_captions") or {}
                )
                for lang in ["en", "fr"]:
                    if lang in subtitles:
                        sub_data = subtitles[lang]
                        if sub_data and isinstance(sub_data, list):
                            data = sub_data[0]
                            if "data" in data:
                                text = data["data"]
                                logger.info(
                                    "transcript_fetched_ytdlp",
                                    video_id=video_id,
                                    chars=len(text),
                                )
                                return text
                return None
        except Exception as e:
            logger.warning("ytdlp_transcript_failed", video_id=video_id, error=str(e))
            return None

    def _get_transcript_api_v3(self, video_id: str) -> str | None:
        try:
            from googleapiclient.errors import HttpError
            from googleapiclient.discovery import build
        except ImportError:
            logger.warning("google_api_client_not_installed", video_id=video_id)
            return None

        try:
            http_auth = self._create_api_v3_auth()
            if http_auth is None:
                return None

            youtube = build("youtube", "v3", http=http_auth)

            captions = (
                youtube.captions().list(part="snippet", videoId=video_id).execute()
            )

            caption_id = None
            for item in captions.get("items", []):
                lang = item.get("snippet", {}).get("language", "")
                if lang in ["en", "fr"]:
                    caption_id = item.get("id")
                    if lang == "en":
                        break

            if not caption_id:
                return None

            caption_data = (
                youtube.captions().download(id=caption_id, tfmt="srt").execute()
            )

            if caption_data:
                text = self._parse_srt_caption(caption_data)
                logger.info(
                    "transcript_fetched_api_v3", video_id=video_id, chars=len(text)
                )
                return text

        except HttpError as e:
            logger.warning("api_v3_http_error", video_id=video_id, status=e.resp.status)
        except Exception as e:
            logger.warning("api_v3_error", video_id=video_id, error=str(e))

        return None

    def _parse_srt_caption(self, srt_data: str) -> str:
        import re

        lines = srt_data.strip().split("\n")
        text_lines = []
        for line in lines:
            line = line.strip()
            if not line or re.match(r"^\d+$", line):
                continue
            if "-->" in line:
                continue
            text_lines.append(line)

        return " ".join(text_lines)

    def _create_api_v3_auth(self):
        try:
            import httplib2
            from google.oauth2.credentials import Credentials

            token_path = Path.home() / ".config" / "youtube-agent" / "token.json"
            if not token_path.exists():
                logger.info("api_v3_token_not_found")
                return None

            creds = Credentials.from_authorized_user_info(
                json.loads(token_path.read_text())
            )
            http = httplib2.Http()
            return creds.authorize(http)
        except Exception as e:
            logger.warning("api_v3_auth_error", error=str(e))
            return None

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
