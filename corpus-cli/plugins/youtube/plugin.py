from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from common import structlog
from common.youtube.transport import RSSPlaylistTransport, Transport
from common.youtube.client import YouTubeClient
from common.youtube.auth import YouTubeOAuth

from core.models import Document
from core.sync_errors import (
    NetworkError,
    TranscriptUnavailableError,
    VideoBlockedError,
)
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
        self._api_client: YouTubeClient | None = None

    def _get_api_client(self, debug: bool = False) -> YouTubeClient:
        if self._api_client is None:
            yt_cfg = self._get_config().get("youtube", {})
            client_secret = yt_cfg.get("client_secret_path")
            if debug:
                logger.info(
                    "DEBUG: Getting YouTube API client",
                    client_secret_path=client_secret is not None,
                    channel_id=self.channel_id,
                )
            oauth = YouTubeOAuth(client_secret_path=client_secret)
            api = oauth.get_client()
            self._api_client = YouTubeClient(
                api, channel_id=self.channel_id, auth=oauth
            )
            if debug:
                logger.info("DEBUG: YouTube API client created successfully")
        return self._api_client

    def _get_config(self) -> dict:
        from common.core.config import load_config

        return load_config()

    def list_items(
        self,
        limit: int,
        known_id_dates: dict[str, datetime | None] | None = None,
        use_api: bool = False,
        non_public: bool = False,
        debug: bool = False,
    ) -> list[ItemMeta]:
        logger.warning(
            "DEBUG: YouTubePlugin.list_items called",
            non_public=non_public,
            use_api=use_api,
            debug=debug,
            limit=limit,
            known_ids_count=len(known_id_dates or {}),
        )

        if non_public:
            if debug:
                logger.info(
                    "DEBUG: Calling _list_items_via_api with include_non_public=True"
                )
            return self._list_items_via_api(
                limit, known_id_dates, include_non_public=True, debug=debug
            )
        if use_api:
            if debug:
                logger.info(
                    "DEBUG: Calling _list_items_via_api with include_non_public=False"
                )
            return self._list_items_via_api(limit, known_id_dates, debug=debug)
        if debug:
            logger.info("DEBUG: Calling _list_items_via_rss")
        return self._list_items_via_rss(limit, known_id_dates, debug=debug)

    def _list_items_via_api(
        self,
        limit: int,
        known_id_dates: dict[str, datetime | None] | None = None,
        include_non_public: bool = False,
        debug: bool = False,
    ) -> list[ItemMeta]:
        from googleapiclient.errors import HttpError

        logger.warning(
            "DEBUG: _list_items_via_api called",
            limit=limit,
            include_non_public=include_non_public,
            debug=debug,
        )

        known = set(known_id_dates or {})
        all_new: list[ItemMeta] = []
        skipped_privacy = 0
        skipped_indexed = 0

        logger.info("youtube_api_list_videos", channel_id=self.channel_id)
        client = self._get_api_client(debug=debug)

        if debug:
            logger.info("DEBUG: YouTube API client initialized successfully")

        max_fetch = limit * 50
        if include_non_public:
            # For non-public videos, we may need to search deeper into the channel history
            # since many recent videos may already be indexed
            max_fetch = max(
                max_fetch, 500
            )  # Fetch more for non-public to find unindexed videos

        try:
            if include_non_public:
                # Fetch videos in batches until we find unindexed ones
                videos = []
                page_token = None
                batch_size = 100
                max_batches = 10  # Limit to avoid excessive API usage

                for batch_num in range(max_batches):
                    if debug:
                        logger.warning(
                            "DEBUG: Fetching batch",
                            batch=batch_num + 1,
                            batch_size=batch_size,
                            total_so_far=len(videos),
                        )

                    batch_videos, page_token = client.get_all_owned_videos(
                        self.channel_id, max_results=batch_size, page_token=page_token
                    )

                    if debug:
                        logger.warning(
                            "DEBUG: Batch returned videos", count=len(batch_videos)
                        )

                    if not batch_videos:
                        break

                    videos.extend(batch_videos)

                    # Count unindexed non-public videos found so far
                    unindexed_non_public = [
                        v for v in videos
                        if v.video_id not in known
                        and (v.privacy_status or "unknown") not in _PUBLIC_STATUSES
                    ]
                    if debug:
                        logger.warning(
                            "DEBUG: Unindexed non-public videos so far",
                            count=len(unindexed_non_public),
                            need=limit,
                        )

                    # Stop once we have enough unindexed non-public videos
                    if len(unindexed_non_public) >= limit:
                        if debug:
                            logger.warning("DEBUG: Found enough non-public unindexed videos, stopping")
                        break

                    # If no more pages, stop
                    if not page_token:
                        if debug:
                            logger.warning("DEBUG: No more pages available")
                        break

                if debug:
                    logger.warning(
                        "DEBUG: Total videos fetched across batches", count=len(videos)
                    )
                    privacy_counts = {}
                    for v in videos:
                        privacy = v.privacy_status or "unknown"
                        privacy_counts[privacy] = privacy_counts.get(privacy, 0) + 1
                    logger.warning("DEBUG: Privacy status breakdown", **privacy_counts)

                yt_cfg = self._get_config().get("youtube", {})
                members_ids = yt_cfg.get("members_video_ids", [])
                if debug:
                    logger.warning(
                        "DEBUG: Members video IDs configured",
                        count=len(members_ids),
                        ids=members_ids,
                    )

                if members_ids:
                    fetched_ids = {v.video_id for v in videos}
                    extra_ids = [vid for vid in members_ids if vid not in fetched_ids]
                    if debug:
                        logger.warning(
                            "DEBUG: Fetching additional member videos",
                            count=len(extra_ids),
                            ids=extra_ids,
                        )
                    if extra_ids:
                        extra = client.get_videos_by_ids(extra_ids)
                        videos.extend(extra)
                        if debug:
                            logger.warning(
                                "DEBUG: Total videos after adding members",
                                total=len(videos),
                            )
            else:
                if debug:
                    logger.info("DEBUG: Fetching public channel videos")
                    logger.info("DEBUG: Max results", max_results=max_fetch)
                videos = client.get_channel_videos(
                    self.channel_id, max_results=max_fetch
                )
                if debug:
                    logger.info("DEBUG: API returned videos", count=len(videos))
        except HttpError as e:
            if e.resp.status == 403 and "quota" in str(e).lower():
                logger.error("youtube_api_quota_exceeded", channel_id=self.channel_id)
                raise RuntimeError(
                    "YouTube API quota exceeded. Try again later or use RSS mode."
                ) from e
            raise

        for video in videos:
            if video.video_id in known:
                skipped_indexed += 1
                continue

            privacy = video.privacy_status or "unknown"

            if include_non_public:
                if privacy in _PUBLIC_STATUSES:
                    continue
            elif not self.index_non_public and privacy not in _PUBLIC_STATUSES:
                logger.info(
                    "video_skipped_privacy",
                    video_id=video.video_id,
                    privacy_status=privacy,
                )
                skipped_privacy += 1
                continue

            duration = 0
            if video.duration:
                match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", video.duration)
                if match:
                    h, m, s = (int(x or 0) for x in match.groups())
                    duration = h * 3600 + m * 60 + s

            try:
                updated = (
                    datetime.fromisoformat(
                        video.published_at.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    if video.published_at
                    else datetime.now()
                )
            except ValueError:
                updated = datetime.now()

            all_new.append(
                ItemMeta(
                    source_id=video.video_id,
                    updated_at=updated,
                    metadata={
                        "id": video.video_id,
                        "title": video.title,
                        "description": video.description,
                        "published_at": video.published_at,
                        "url": video.url,
                        "duration_seconds": duration,
                        "privacy_status": privacy,
                    },
                )
            )

        if debug and all_new:
            # Calculate date range
            dates = [item.updated_at for item in all_new if item.updated_at]
            if dates:
                min_date = min(dates)
                max_date = max(dates)
                logger.info(
                    "DEBUG: Date range of videos found",
                    min_date=min_date.isoformat(),
                    max_date=max_date.isoformat(),
                )
            logger.info(
                "DEBUG: Sample video metadata",
                video_0=all_new[0].metadata if all_new else None,
            )

        logger.info(
            "api_fetched",
            source=self.name,
            total_api=len(videos),
            already_indexed=skipped_indexed,
            skipped_privacy=skipped_privacy,
            new_available=len(all_new),
        )

        out = all_new[:limit]
        for item in out:
            logger.info(
                "video_listed",
                video_id=item.source_id,
                title=item.metadata.get("title", ""),
                duration=_format_duration(item.metadata.get("duration_seconds", 0)),
                privacy_status=item.metadata.get("privacy_status", "unknown"),
            )

        if skipped_privacy:
            logger.info("videos_skipped_non_public", count=skipped_privacy)
        logger.info("items_listed", source=self.name, count=len(out), requested=limit)
        return out

    def _list_items_via_rss(
        self,
        limit: int,
        known_id_dates: dict[str, datetime | None] | None = None,
        debug: bool = False,
    ) -> list[ItemMeta]:
        known = set(known_id_dates or {})
        all_new: list[ItemMeta] = []
        skipped_privacy = 0
        skipped_indexed = 0

        if debug:
            logger.info("DEBUG: Using RSS feed for video listing")
            logger.info("DEBUG: Channel ID", channel_id=self.channel_id)

        playlist_id = self.transport.get_uploads_playlist(self.channel_id)

        if debug:
            logger.info("DEBUG: Uploads playlist ID", playlist_id=playlist_id)

        for page in self.transport.iter_playlist_pages(playlist_id):
            video_ids = [item["snippet"]["resourceId"]["videoId"] for item in page]
            details = self.transport.get_video_details(video_ids)

            for item in page:
                snippet = item["snippet"]
                video_id = snippet["resourceId"]["videoId"]

                if video_id in known:
                    skipped_indexed += 1
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

                all_new.append(
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

        logger.info(
            "rss_fetched",
            source=self.name,
            total_rss=len(all_new) + skipped_indexed + skipped_privacy,
            already_indexed=skipped_indexed,
            skipped_privacy=skipped_privacy,
            new_available=len(all_new),
        )

        out = all_new[:limit]
        for item in out:
            logger.info(
                "video_listed",
                video_id=item.source_id,
                title=item.metadata.get("title", ""),
                duration=_format_duration(item.metadata.get("duration_seconds", 0)),
                privacy_status=item.metadata.get("privacy_status", "unknown"),
            )

        if skipped_privacy:
            logger.info("videos_skipped_non_public", count=skipped_privacy)
        logger.info("items_listed", source=self.name, count=len(out), requested=limit)
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

        is_non_public = privacy_status not in _PUBLIC_STATUSES

        transcript = None
        last_error = None

        if is_non_public:
            logger.info("non_public_video_using_api_captions", video_id=video_id)
        else:
            # Fallback 1: youtube-transcript-api (only for public videos)
            try:
                transcript = self.transport.get_transcript(video_id, self.cookies)
            except VideoBlockedError as exc:
                logger.info("transcript_api_blocked_trying_yt_dlp", video_id=video_id)
                last_error = exc
            except TranscriptUnavailableError:
                logger.info("transcript_unavailable_trying_yt_dlp", video_id=video_id)
            except Exception as exc:
                logger.warning(
                    "transcript_api_error", video_id=video_id, error=str(exc)[:100]
                )
                last_error = exc

            # Fallback 2: yt-dlp subtitles (only for public videos)
            if transcript is None:
                try:
                    transcript = self._try_yt_dlp_subs(video_id)
                except Exception as exc:
                    logger.info(
                        "yt_dlp_subs_failed", video_id=video_id, error=str(exc)[:100]
                    )
                    last_error = exc

        # Fallback 3: YouTube API captions (works for all videos)
        if transcript is None:
            try:
                transcript = self._try_youtube_api_captions(video_id)
            except Exception as exc:
                logger.info(
                    "youtube_api_captions_failed",
                    video_id=video_id,
                    error=str(exc)[:100],
                )
                last_error = exc

        # Fallback 4: whisper (download audio + transcribe)
        if transcript is None:
            try:
                transcript = self._try_whisper(video_id)
            except Exception as exc:
                logger.info("whisper_failed", video_id=video_id, error=str(exc)[:100])
                last_error = exc

        # If all fallbacks failed
        if transcript is None:
            raise VideoBlockedError(
                f"All transcript methods failed for {video_id}: {last_error}"
            )

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

    def _try_yt_dlp_subs(self, video_id: str) -> str | None:
        """Try to get subtitles using yt-dlp."""
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("pip install yt-dlp") from exc

        import tempfile
        from pathlib import Path

        out_dir = Path(tempfile.mkdtemp())
        ydl_opts: dict = {
            "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "write_subs": True,
            "write_auto_subs": True,
            "skip_download": True,
            "subtitleslangs": ["en", "fr"],
        }
        if self.cookies:
            ydl_opts["cookiefile"] = self.cookies

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        except Exception as exc:
            logger.info(
                "yt_dlp_subs_download_failed", video_id=video_id, error=str(exc)[:100]
            )
            return None

        # Look for subtitle files
        for ext in ["srt", "vtt", "txt"]:
            subs = list(out_dir.glob(f"*.{ext}"))
            if subs:
                text = subs[0].read_text(encoding="utf-8")
                # Simple cleanup - extract text from srt/vtt
                if ext == "srt":
                    import re

                    text = re.sub(r"\d+\n\d{2}:\d{2}:\d{2},\d{3} --> .*\n", "", text)
                elif ext == "vtt":
                    import re

                    text = re.sub(r"WEBVTT\n.*\n\n", "", text)
                text = text.strip()
                if text:
                    logger.info(
                        "yt_dlp_subs_success", video_id=video_id, chars=len(text)
                    )
                    return text

        logger.info("yt_dlp_no_subs_found", video_id=video_id)
        return None

    def _try_youtube_api_captions(self, video_id: str) -> str | None:
        """Try to get captions using YouTube Data API."""
        try:
            client = self._get_api_client()
            yt = client.youtube
        except Exception as exc:
            logger.warning(
                "youtube_api_client_failed", video_id=video_id, error=str(exc)[:100]
            )
            raise RuntimeError(
                "YouTube API not available. Ensure OAuth credentials are configured "
                "with 'https://www.googleapis.com/auth/youtube.force-ssl' scope. "
                f"Error: {exc}"
            ) from exc

        try:
            # List captions
            captions = yt.captions().list(part="snippet", videoId=video_id).execute()

            if not captions.get("items"):
                logger.info("youtube_api_no_captions", video_id=video_id)
                return None

            # Get the first available caption track
            caption_id = captions["items"][0]["id"]

            # Download caption
            caption = yt.captions().download(id=caption_id, tfmt="srt").execute()

            if caption:
                import re

                text = (
                    caption.decode("utf-8")
                    if isinstance(caption, bytes)
                    else str(caption)
                )
                # Convert SRT to plain text
                text = re.sub(r"\d+\n\d{2}:\d{2}:\d{2},\d{3} --> .*\n", "", text)
                text = text.strip()
                logger.info(
                    "youtube_api_captions_success", video_id=video_id, chars=len(text)
                )
                return text

        except Exception as exc:
            error_msg = str(exc).lower()
            if "not found" in error_msg or "closed" in error_msg:
                logger.info("youtube_api_no_captions", video_id=video_id)
                return None
            if "scope" in error_msg or "permission" in error_msg:
                raise RuntimeError(
                    "YouTube API missing required scope. "
                    "Re-authenticate with: "
                    "https://console.cloud.google.com/apis/credentials "
                    "Ensure token has 'https://www.googleapis.com/auth/youtube.force-ssl' scope."
                ) from exc
            raise

        return None

    def _try_whisper(self, video_id: str) -> str | None:
        """Try to transcribe using whisper (download audio + transcribe)."""
        logger.info("transcript_unavailable_trying_whisper", video_id=video_id)
        audio = self.transport.download_audio(video_id, self.cookies)
        if audio is None:
            return None
        try:
            transcript = transcribe_audio(audio, self.whisper_model)
            return transcript
        except OSError as exc:
            raise NetworkError(f"Network error while transcribing {video_id}") from exc


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
