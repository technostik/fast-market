from __future__ import annotations

import re
import time
import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor

import feedparser
import yt_dlp

from plugins.base import SourcePlugin, ItemMetadata


class YouTubePlugin(SourcePlugin):
    name = "youtube"

    def __init__(self, config: dict, source_config: dict):
        super().__init__(config, source_config)
        self.channel_id = self._resolve_channel_id(source_config["identifier"])
        self.executor = ThreadPoolExecutor(max_workers=5)  # For running yt-dlp sync calls
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_generic_extractor': False,
            'ignoreerrors': True,
            'no_color': True,
            'geo_bypass': True,
        }

    def _resolve_channel_id(self, identifier: str) -> str:
        """Resolve various YouTube identifier formats to channel ID"""
        # Clean the identifier
        identifier = identifier.strip()

        # Already a channel ID
        if identifier.startswith("UC") and len(identifier) == 24:
            return identifier

        # Handle handle format (@username)
        if identifier.startswith("@"):
            # For handles, we still need to resolve via API or fallback
            # This is a simplified version - ideally you'd use the YouTube API
            # or implement handle resolution via webpage scraping
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
                # If it's a custom URL or handle, we'd need to resolve it
                # For now, raise error
                raise NotImplementedError(
                    f"Custom URL/handle resolution not implemented. "
                    f"Extracted: {match.group(1)}\n"
                    f"Please use channel ID directly."
                )

        raise ValueError(f"Invalid YouTube identifier: {identifier}")

    async def _get_video_details_async(self, video_id: str) -> dict:
        """Get detailed video info using yt-dlp (async wrapper)"""
        url = f"https://youtube.com/watch?v={video_id}"

        loop = asyncio.get_event_loop()
        try:
            # Run yt-dlp in thread pool since it's blocking
            info = await loop.run_in_executor(
                self.executor,
                self._extract_video_info,
                url
            )
            return info
        except Exception as e:
            print(f"Error getting video details for {video_id}: {e}")
            return {}

    def _extract_video_info(self, url: str) -> dict:
        """Synchronous yt-dlp extraction"""
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)

                if not info:
                    return {}

                # Parse upload date
                upload_date = None
                if info.get('upload_date'):
                    try:
                        upload_date = datetime.strptime(
                            info['upload_date'], '%Y%m%d'
                        ).replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass

                # Get like count (may be None for some videos)
                like_count = info.get('like_count')
                if like_count is None and 'like_count' in info:
                    like_count = 0

                # Get comment count
                comment_count = info.get('comment_count')
                if comment_count is None:
                    comment_count = 0

                # Determine if it's a Short
                duration = info.get('duration', 0)
                is_short = duration < 60 or info.get('webpage_url_basename') == 'shorts'

                return {
                    'duration_seconds': duration,
                    'views': info.get('view_count', 0),
                    'likes': like_count,
                    'comments': comment_count,
                    'upload_date': upload_date,
                    'is_short': is_short,
                    'channel_id': info.get('channel_id', ''),
                    'channel_name': info.get('channel', info.get('uploader', '')),
                    'channel_url': info.get('channel_url', ''),
                    'description': info.get('description', '')[:500],  # Truncate description
                    'tags': info.get('tags', [])[:10],  # Limit tags
                    'categories': info.get('categories', []),
                    'age_limit': info.get('age_limit', 0),
                    'availability': info.get('availability', 'public'),
                }
            except Exception as e:
                print(f"yt-dlp extraction error: {e}")
                return {}

    def _parse_feed_entry(self, entry: feedparser.FeedParserDict, feed_title: str) -> dict:
        """Parse feed entry for basic metadata"""
        # Get video ID from various possible locations
        vid_id = None
        if hasattr(entry, 'yt_videoid'):
            vid_id = entry.yt_videoid
        elif hasattr(entry, 'id') and 'video:' in entry.id:
            vid_id = entry.id.split('video:')[-1]
        elif hasattr(entry, 'link'):
            # Extract from link
            match = re.search(r"v=([a-zA-Z0-9_-]+)", entry.link)
            if match:
                vid_id = match.group(1)

        # Parse published date
        published = datetime.now(timezone.utc)
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                published = datetime.fromtimestamp(
                    time.mktime(entry.published_parsed), tz=timezone.utc
                )
            except (OverflowError, ValueError, TypeError):
                pass

        # Get duration from media content if available
        duration = 0
        if hasattr(entry, 'media_content') and entry.media_content:
            try:
                duration = int(entry.media_content[0].get('duration', 0))
            except (ValueError, TypeError):
                pass

        return {
            'id': vid_id,
            'title': entry.get('title', 'Untitled'),
            'url': entry.get('link', f'https://youtube.com/watch?v={vid_id}'),
            'published': published,
            'duration': duration,
            'author': entry.get('author', ''),
            'summary': entry.get('summary', '')[:200],
        }

    async def fetch_new_items(
        self,
        last_item_id: str | None = None,
        limit: int = 50,
        last_fetched_at: datetime | None = None,
    ) -> list[ItemMetadata]:
        """Fetch new videos from YouTube channel"""
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={self.channel_id}"

        try:
            # Parse RSS feed
            feed = feedparser.parse(rss_url)

            if hasattr(feed, 'bozo_exception'):
                print(f"RSS feed parsing error: {feed.bozo_exception}")

            items = []
            feed_title = getattr(feed.feed, 'title', '')

            # Process entries
            for entry in feed.entries[:limit]:
                # Parse basic info from feed
                parsed = self._parse_feed_entry(entry, feed_title)

                if not parsed['id']:
                    continue

                # Check if we've reached last fetched item
                if last_item_id and parsed['id'] == last_item_id:
                    break

                if last_fetched_at and parsed['published'] <= last_fetched_at:
                    break

                # Get detailed info with yt-dlp
                details = await self._get_video_details_async(parsed['id'])

                # Merge data, preferring yt-dlp data where available
                extra = {
                    'channel_id': self.channel_id,
                    'channel_name': details.get('channel_name', feed_title),
                    'duration_seconds': details.get('duration_seconds', parsed['duration']),
                    'is_short': details.get('is_short', parsed['duration'] < 60),
                    'views': details.get('views', 0),
                    'likes': details.get('likes', 0),
                    'comments': details.get('comments', 0),
                    'description': details.get('description', parsed['summary']),
                    'tags': details.get('tags', []),
                    'categories': details.get('categories', []),
                    'age_limit': details.get('age_limit', 0),
                    'availability': details.get('availability', 'public'),
                }

                # Use more accurate upload date if available
                published_at = details.get('upload_date', parsed['published'])

                # Determine content type
                content_type = 'short' if extra['is_short'] else 'video'
                if extra['duration_seconds'] > 3600:
                    content_type = 'long_video'

                item = ItemMetadata(
                    id=parsed['id'],
                    title=parsed['title'],
                    url=parsed['url'],
                    published_at=published_at,
                    content_type=content_type,
                    source_plugin=self.name,
                    source_identifier=self.channel_id,
                    raw={
                        'rss_entry': entry.__dict__ if hasattr(entry, '__dict__') else {},
                        'yt_dlp': details,
                    },
                    extra=extra,
                )

                items.append(item)

                # Small delay to avoid rate limiting
                await asyncio.sleep(0.1)

            return items

        except Exception as e:
            print(f"Error fetching YouTube items: {e}")
            return []

    async def get_video_comments(
        self,
        video_id: str,
        max_comments: int = 100
    ) -> list[dict]:
        """Fetch comments for a specific video"""
        url = f"https://youtube.com/watch?v={video_id}"

        # yt-dlp options for comments
        ydl_opts = {
            **self.ydl_opts,
            'getcomments': True,
            'extract_flat': True,  # Don't download video
            'max_comments': max_comments,
        }

        loop = asyncio.get_event_loop()

        def _extract_comments():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                    comments = info.get('comments', [])

                    # Format comments
                    formatted_comments = []
                    for comment in comments[:max_comments]:
                        formatted_comments.append({
                            'id': comment.get('id'),
                            'author': comment.get('author'),
                            'author_id': comment.get('author_id'),
                            'text': comment.get('text', ''),
                            'timestamp': comment.get('timestamp'),
                            'likes': comment.get('like_count', 0),
                            'reply_count': comment.get('reply_count', 0),
                        })
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

        # Check for direct channel ID
        if identifier.startswith("UC") and len(identifier) == 24:
            return True

        # Check for handle
        if identifier.startswith("@"):
            return True

        # Check for URLs
        url_patterns = [
            r"youtube\.com/channel/UC[a-zA-Z0-9_-]+",
            r"youtube\.com/c/[^/?#&]+",
            r"youtube\.com/user/[^/?#&]+",
            r"youtube\.com/@[^/?#&]+",
            r"youtu\.be/",  # Video URL, not channel
        ]

        for pattern in url_patterns:
            if re.search(pattern, identifier):
                return True

        return False

    def get_identifier_display(self, identifier: str) -> str:
        """Return a user-friendly display version of the identifier"""
        identifier = identifier.strip()

        # If it's a channel ID, add a label
        if identifier.startswith("UC") and len(identifier) == 24:
            return f"Channel ID: {identifier}"

        # If it's a handle, format nicely
        if identifier.startswith("@"):
            return f"YouTube Handle: {identifier}"

        # Try to extract username from URL for cleaner display
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
