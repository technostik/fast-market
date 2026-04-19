from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import yt_dlp

from plugins.base import ItemMetadata, SourcePlugin


class YouTubeSearchPlugin(SourcePlugin):
    name = "yt-search"

    DEFAULT_MIN_VIEWS = 1000
    DEFAULT_MAX_RESULTS = 50

    def __init__(self, config: dict, source_config: dict):
        super().__init__(config, source_config)
        self.source_id = source_config.get("id", "")
        self.keywords = source_config["origin"].strip()
        self.min_views = int(self.metadata.get("min_views", self.DEFAULT_MIN_VIEWS))
        self.max_results = int(self.metadata.get("max_results", self.DEFAULT_MAX_RESULTS))
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "force_generic_extractor": False,
            "ignoreerrors": True,
            "no_color": True,
            "geo_bypass": True,
            "skip_download": True,
        }

    def _search_via_yt_dlp(self, keywords: str, limit: int) -> list[dict]:
        search_url = f"ytsearch{limit}:{keywords}"

        def _extract():
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(search_url, download=False)
                    if not info:
                        return []
                    entries = info.get("entries", []) or []
                    videos = []
                    for entry in entries:
                        if not entry:
                            continue
                        video_id = entry.get("id")
                        if not video_id:
                            continue

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

                        is_short = "/shorts/" in entry_url
                        if not is_short and 0 < duration < 180:
                            is_short = True

                        channel_id = entry.get("channel_id", "")
                        channel_name = entry.get("channel", entry.get("uploader", ""))

                        videos.append(
                            {
                                "id": video_id,
                                "title": entry.get("title", "Untitled"),
                                "url": entry_url,
                                "published": upload_date,
                                "duration": duration,
                                "channel_id": channel_id,
                                "channel_name": channel_name,
                                "views": entry.get("view_count") or 0,
                                "likes": entry.get("like_count") or 0,
                                "comments": entry.get("comment_count") or 0,
                                "description": (entry.get("description") or "")[:500],
                                "tags": (entry.get("tags") or [])[:10],
                                "categories": entry.get("categories") or [],
                                "is_short": is_short,
                                "availability": entry.get("availability", "public"),
                            }
                        )
                    return videos
                except Exception as e:
                    print(f"yt-dlp search extraction error for '{keywords}': {e}")
                    return []

        try:
            return self.executor.submit(_extract).result(timeout=60)
        except Exception as e:
            print(f"yt-dlp search failed for '{keywords}': {e}")
            return []

    def _filter_by_views(self, videos: list[dict]) -> list[dict]:
        if self.min_views <= 0:
            return videos
        return [v for v in videos if v.get("views", 0) >= self.min_views]

    async def fetch_new_items(
        self,
        last_item_id: str | None = None,
        limit: int = 50,
        force: bool = False,
        seen_item_ids: set[str] | None = None,
        date_filter: str | None = None,
    ) -> list[ItemMetadata]:
        if not self._should_fetch(force):
            return []

        effective_limit = min(self.max_results, limit)

        loop = asyncio.get_event_loop()
        try:
            videos = await loop.run_in_executor(
                self.executor, lambda: self._search_via_yt_dlp(self.keywords, effective_limit)
            )
        except Exception as e:
            print(f"Search fetch failed for '{self.keywords}': {e}")
            return []

        videos = self._filter_by_views(videos)

        videos.sort(key=lambda v: v["published"], reverse=True)

        today = None
        if date_filter == "today":
            today = datetime.now(timezone.utc).date()

        items = []
        for video in videos:
            if today:
                try:
                    upload_date = datetime.strptime(video["upload_date"], "%Y%m%d").date()
                    if upload_date != today:
                        continue
                except (ValueError, KeyError):
                    continue

            if last_item_id and video["id"] == last_item_id:
                break

            extra = {
                "search_keywords": self.keywords,
                "channel_id": video["channel_id"],
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
                "min_views_threshold": self.min_views,
                "slowdown": self.slowdown,
            }

            if extra["is_short"]:
                content_type = "short"
            elif video["duration"] > 3600:
                content_type = "long_video"
            elif video["duration"] > 600:
                content_type = "medium_video"
            else:
                content_type = "video"
                content_type = "long_video"

            items.append(
                ItemMetadata(
                    id=video["id"],
                    title=video["title"],
                    url=video["url"],
                    published_at=video["published"],
                    content_type=content_type,
                    source_plugin=self.name,
                    source_id=self.source_id,
                    extra=extra,
                )
            )

        return items

    def validate_identifier(self, identifier: str) -> bool:
        identifier = identifier.strip()
        if not identifier:
            return False
        if len(identifier) > 500:
            return False
        dangerous_patterns = [
            r"^\s*rm\s",
            r"^\s*del\s",
            r"^\s*rmrf",
            r"^\s*sudo",
            r"^\s*>\s*/dev/",
        ]
        for pattern in dangerous_patterns:
            if re.match(pattern, identifier, re.IGNORECASE):
                return False
        return True

    def get_identifier_display(self, identifier: str) -> str:
        keywords = identifier.strip()
        if len(keywords) > 50:
            return f'Search: "{keywords[:50]}..."'
        return f'Search: "{keywords}"'

    async def close(self):
        self.executor.shutdown(wait=False)
