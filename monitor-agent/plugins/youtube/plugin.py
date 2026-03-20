from __future__ import annotations

import re
import time
import asyncio
from datetime import datetime, timezone
from typing import Any
from concurrent.futures import ThreadPoolExecutor

import feedparser
import requests
import yt_dlp
from requests.exceptions import RequestException

from plugins.base import SourcePlugin, ItemMetadata


class YouTubePlugin(SourcePlugin):
    name = "youtube"

    def __init__(self, config: dict, source_config: dict):
        super().__init__(config, source_config)
        self.channel_id = self._resolve_channel_id(source_config["identifier"])
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,  # Changed to True for playlist extraction
            "force_generic_extractor": False,
            "ignoreerrors": True,
            "no_color": True,
            "geo_bypass": True,
        }
        # Separate options for detailed video info
        self.detail_ydl_opts = {
            **self.ydl_opts,
            "extract_flat": False,
        }

    def _resolve_channel_id(self, identifier: str) -> str:
        """Resolve various YouTube identifier formats to channel ID"""
        identifier = identifier.strip()

        # Already a channel ID
        if identifier.startswith("UC") and len(identifier) == 24:
            return identifier

        # Handle handle format (@username)
        if identifier.startswith("@"):
            raise NotImplementedError(
                "YouTube handle resolution requires API key. "
                "Use channel ID directly or set up YouTube API.\n"
                f"To find channel ID: https://commentpicker.com/youtube-channel-id.php"
            )

        # Extract from URL patterns
        url_patterns = [
            r"youtube\.com/channel/(UC[a-zA-Z0-9_-]+)",
            r"youtube\.com/c/([^/?#&]+)",
            r"youtube\.com/user/([^/?#&]+)",
            r"youtube\.com/@([^/?#&]+)",
        ]

        for pattern in url_patterns:
            match = re.search(pattern, identifier)
            if match:
                if "UC" in match.group(1) and match.group(1).startswith("UC"):
                    return match.group(1)
                raise NotImplementedError(
                    f"Custom URL/handle resolution not implemented. "
                    f"Extracted: {match.group(1)}\n"
                    f"Please use channel ID directly."
                )

        raise ValueError(f"Invalid YouTube identifier: {identifier}")

    def _check_rss_availability(self, rss_url: str) -> bool:
        """Check if RSS feed is available (returns 200)"""
        try:
            response = requests.head(
                rss_url,
                timeout=5,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; monitor-agent/1.0)"},
            )
            return response.status_code == 200
        except RequestException:
            return False

    async def _fetch_via_yt_dlp(
        self, last_item_id: str | None = None, limit: int = 50
    ) -> list[ItemMetadata]:
        """Fetch videos and shorts using yt-dlp as fallback when RSS fails"""
        videos_url = f"https://www.youtube.com/channel/{self.channel_id}/videos"
        shorts_url = f"https://www.youtube.com/channel/{self.channel_id}/shorts"

        loop = asyncio.get_event_loop()

        def _extract_videos(url, is_short_playlist=False):
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        return []
                    entries = info.get("entries", []) or []
                    channel_name = info.get("channel", info.get("uploader", ""))
                    videos = []
                    for entry in entries[:limit]:
                        if not entry:
                            continue
                        video_id = entry.get("id")
                        if not video_id:
                            continue
                        if last_item_id and video_id == last_item_id:
                            break
                        upload_date = None
                        if entry.get("upload_date"):
                            try:
                                upload_date = datetime.strptime(
                                    entry["upload_date"], "%Y%m%d"
                                ).replace(tzinfo=timezone.utc)
                            except ValueError:
                                upload_date = datetime.now(timezone.utc)
                        else:
                            upload_date = datetime.now(timezone.utc)
                        duration = entry.get("duration") or 0
                        entry_url = entry.get("url", f"https://www.youtube.com/watch?v={video_id}")
                        if "/shorts/" not in entry_url and "watch?v=" not in entry_url:
                            entry_url = f"https://www.youtube.com/watch?v={video_id}"
                        is_short = "/shorts/" in entry_url or is_short_playlist
                        if not is_short and 0 < duration < 180:
                            is_short = True
                        videos.append(
                            {
                                "id": video_id,
                                "title": entry.get("title", "Untitled"),
                                "url": entry_url,
                                "published": upload_date,
                                "duration": duration,
                                "channel_name": channel_name,
                                "views": entry.get("view_count") or 0,
                                "likes": entry.get("like_count") or 0,
                                "comments": entry.get("comment_count") or 0,
                                "description": (entry.get("description") or "")[:500],
                                "tags": (entry.get("tags") or [])[:10],
                                "categories": entry.get("categories") or [],
                                "is_short": is_short,
                                "availability": entry.get("availability"),
                            }
                        )
                    return videos
                except Exception as e:
                    print(f"yt-dlp extraction error for {url}: {e}")
                    return []

        try:
            all_videos = await loop.run_in_executor(
                self.executor, lambda: _extract_videos(videos_url)
            )
            all_shorts = await loop.run_in_executor(
                self.executor, lambda: _extract_videos(shorts_url, is_short_playlist=True)
            )
            videos = all_videos + all_shorts
            videos.sort(key=lambda v: v["published"], reverse=True)
            videos = videos[:limit]

            items = []
            for video in videos:
                extra = {
                    "channel_id": self.channel_id,
                    "channel_name": video["channel_name"],
                    "duration_seconds": video["duration"],
                    "is_short": video["is_short"],
                    "views": video["views"],
                    "likes": video["likes"],
                    "comments": video["comments"],
                    "description": video["description"],
                    "tags": video["tags"],
                    "categories": video["categories"],
                    "availability": video["availability"],
                    "fetch_method": "yt-dlp",
                }

                if extra["is_short"]:
                    content_type = "short"
                elif video["duration"] > 3600:
                    content_type = "long_video"
                elif video["duration"] > 600:
                    content_type = "medium_video"
                else:
                    content_type = "video"

                items.append(
                    ItemMetadata(
                        id=video["id"],
                        title=video["title"],
                        url=video["url"],
                        published_at=video["published"],
                        content_type=content_type,
                        source_plugin=self.name,
                        source_identifier=self.channel_id,
                        raw={"yt_dlp": video},
                        extra=extra,
                    )
                )

            return items

        except Exception as e:
            raise Exception(f"yt-dlp fallback failed: {e}")

    async def _get_video_details_async(self, video_id: str) -> dict:
        """Get detailed video info using yt-dlp (async wrapper)"""
        url = f"https://youtube.com/watch?v={video_id}"

        loop = asyncio.get_event_loop()
        try:
            info = await loop.run_in_executor(self.executor, self._extract_video_info, url)
            return info
        except Exception as e:
            print(f"Error getting video details for {video_id}: {e}")
            return {}

    def _extract_video_info(self, url: str) -> dict:
        """Synchronous yt-dlp extraction for detailed video info"""
        with yt_dlp.YoutubeDL(self.detail_ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)

                if not info:
                    return {}

                upload_date = None
                if info.get("upload_date"):
                    try:
                        upload_date = datetime.strptime(info["upload_date"], "%Y%m%d").replace(
                            tzinfo=timezone.utc
                        )
                    except ValueError:
                        pass

                like_count = info.get("like_count")
                if like_count is None:
                    like_count = 0

                comment_count = info.get("comment_count", 0)
                duration = info.get("duration", 0)
                is_short = duration < 180 or info.get("webpage_url_basename") == "shorts"

                return {
                    "duration_seconds": duration,
                    "views": info.get("view_count", 0),
                    "likes": like_count,
                    "comments": comment_count,
                    "upload_date": upload_date,
                    "is_short": is_short,
                    "channel_id": info.get("channel_id", ""),
                    "channel_name": info.get("channel", info.get("uploader", "")),
                    "channel_url": info.get("channel_url", ""),
                    "description": info.get("description", "")[:500],
                    "tags": info.get("tags", [])[:10],
                    "categories": info.get("categories", []),
                    "age_limit": info.get("age_limit", 0),
                    "availability": info.get("availability", "public"),
                }
            except Exception as e:
                print(f"yt-dlp extraction error: {e}")
                return {}

    def _parse_feed_entry(self, entry: feedparser.FeedParserDict, feed_title: str) -> dict:
        """Parse feed entry for basic metadata"""
        vid_id = None
        if hasattr(entry, "yt_videoid"):
            vid_id = entry.yt_videoid
        elif hasattr(entry, "id") and "video:" in entry.id:
            vid_id = entry.id.split("video:")[-1]
        elif hasattr(entry, "link"):
            match = re.search(r"v=([a-zA-Z0-9_-]+)", entry.link)
            if match:
                vid_id = match.group(1)

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

        video_url = f"https://youtube.com/watch?v={vid_id}" if vid_id else ""
        if hasattr(entry, "link") and entry.link:
            if "watch?v=" in entry.link:
                video_url = entry.link
            elif vid_id:
                video_url = f"https://youtube.com/watch?v={vid_id}"

        return {
            "id": vid_id,
            "title": entry.get("title", "Untitled"),
            "url": video_url,
            "published": published,
            "duration": duration,
            "author": entry.get("author", ""),
            "summary": entry.get("summary", "")[:200],
        }

    async def fetch_new_items(
        self,
        last_item_id: str | None = None,
        limit: int = 50,
        last_fetched_at: datetime | None = None,
        force: bool = False,
    ) -> list[ItemMetadata]:
        """Fetch new videos from YouTube channel with RSS fallback to yt-dlp"""
        if not self._should_fetch(force):
            return []

        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={self.channel_id}"

        # First check if RSS is available
        rss_available = self._check_rss_availability(rss_url)

        if not rss_available:
            print(f"⚠️ RSS feed not available for {self.channel_id}, falling back to yt-dlp")
            return await self._fetch_via_yt_dlp(last_item_id, limit)

        # Try RSS first
        try:
            feed = feedparser.parse(rss_url)

            if hasattr(feed, "bozo_exception") and feed.bozo_exception:
                # RSS parsing failed, fall back to yt-dlp
                print(f"⚠️ RSS parsing failed for {self.channel_id}, falling back to yt-dlp")
                return await self._fetch_via_yt_dlp(last_item_id, limit)

            items = []
            feed_title = getattr(feed.feed, "title", "")

            for entry in feed.entries[:limit]:
                parsed = self._parse_feed_entry(entry, feed_title)

                if not parsed["id"]:
                    continue

                if last_item_id and parsed["id"] == last_item_id:
                    break

                if last_fetched_at and parsed["published"] <= last_fetched_at:
                    break

                # Get detailed info with yt-dlp
                details = await self._get_video_details_async(parsed["id"])

                extra = {
                    "channel_id": self.channel_id,
                    "channel_name": details.get("channel_name", feed_title),
                    "duration_seconds": details.get("duration_seconds", parsed["duration"]),
                    "is_short": details.get("is_short", parsed["duration"] < 180),
                    "views": details.get("views", 0),
                    "likes": details.get("likes", 0),
                    "comments": details.get("comments", 0),
                    "description": details.get("description", parsed["summary"]),
                    "tags": details.get("tags", []),
                    "categories": details.get("categories", []),
                    "age_limit": details.get("age_limit", 0),
                    "availability": details.get("availability", "public"),
                    "fetch_method": "rss+yt-dlp",
                }

                published_at = details.get("upload_date", parsed["published"])
                if extra["is_short"]:
                    content_type = "short"
                elif extra["duration_seconds"] > 3600:
                    content_type = "long_video"
                elif extra["duration_seconds"] > 600:
                    content_type = "medium_video"
                else:
                    content_type = "video"

                items.append(
                    ItemMetadata(
                        id=parsed["id"],
                        title=parsed["title"],
                        url=parsed["url"],
                        published_at=published_at,
                        content_type=content_type,
                        source_plugin=self.name,
                        source_identifier=self.channel_id,
                        raw={"rss_entry": entry.__dict__ if hasattr(entry, "__dict__") else {}},
                        extra=extra,
                    )
                )

                await asyncio.sleep(0.1)

            return items

        except Exception as e:
            # Any other error, try yt-dlp as fallback
            print(f"⚠️ RSS fetch failed for {self.channel_id}: {e}, falling back to yt-dlp")
            return await self._fetch_via_yt_dlp(last_item_id, limit)

    async def get_video_comments(self, video_id: str, max_comments: int = 100) -> list[dict]:
        """Fetch comments for a specific video"""
        url = f"https://youtube.com/watch?v={video_id}"

        comment_opts = {
            **self.detail_ydl_opts,
            "getcomments": True,
            "max_comments": max_comments,
        }

        loop = asyncio.get_event_loop()

        def _extract_comments():
            with yt_dlp.YoutubeDL(comment_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                    comments = info.get("comments", [])

                    formatted_comments = []
                    for comment in comments[:max_comments]:
                        formatted_comments.append(
                            {
                                "id": comment.get("id"),
                                "author": comment.get("author"),
                                "author_id": comment.get("author_id"),
                                "text": comment.get("text", ""),
                                "timestamp": comment.get("timestamp"),
                                "likes": comment.get("like_count", 0),
                                "reply_count": comment.get("reply_count", 0),
                            }
                        )
                    return formatted_comments
                except Exception as e:
                    print(f"Error extracting comments: {e}")
                    return []

        try:
            comments = await loop.run_in_executor(self.executor, _extract_comments)
            return comments
        except Exception as e:
            print(f"Error fetching comments: {e}")
            return []

    def validate_identifier(self, identifier: str) -> bool:
        """Validate if identifier is a supported YouTube format"""
        identifier = identifier.strip()

        if identifier.startswith("UC") and len(identifier) == 24:
            return True

        if identifier.startswith("@"):
            return True

        url_patterns = [
            r"youtube\.com/channel/UC[a-zA-Z0-9_-]+",
            r"youtube\.com/c/[^/?#&]+",
            r"youtube\.com/user/[^/?#&]+",
            r"youtube\.com/@[^/?#&]+",
            r"youtu\.be/",
        ]

        for pattern in url_patterns:
            if re.search(pattern, identifier):
                return True

        return False

    def get_identifier_display(self, identifier: str) -> str:
        """Return a user-friendly display version of the identifier"""
        identifier = identifier.strip()

        if identifier.startswith("UC") and len(identifier) == 24:
            return f"Channel ID: {identifier}"

        if identifier.startswith("@"):
            return f"YouTube Handle: {identifier}"

        patterns = [
            (r"youtube\.com/channel/(UC[a-zA-Z0-9_-]+)", r"Channel: \1"),
            (r"youtube\.com/c/([^/?#&]+)", r"Custom URL: \1"),
            (r"youtube\.com/user/([^/?#&]+)", r"User: \1"),
            (r"youtube\.com/@([^/?#&]+)", r"Handle: @\1"),
        ]

        for pattern, replacement in patterns:
            match = re.search(pattern, identifier)
            if match:
                return re.sub(pattern, replacement, identifier)

        return identifier

    async def close(self):
        """Clean up resources"""
        self.executor.shutdown(wait=False)
