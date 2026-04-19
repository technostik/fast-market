from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import click

from common import structlog
from common.youtube.models import (
    ChannelInfo,
    Comment,
    CommentResult,
    ReplyResult,
    Video,
)
from common.youtube.quota import QuotaTracker
from common.youtube.utils import format_count, is_short_video, iso_duration_to_seconds

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource

logger = structlog.get_logger(__name__)


def _is_insufficient_permissions_error(e: HttpError) -> bool:
    """Check if an HttpError is an insufficientPermissions error."""
    if e.resp.status != 403:
        return False
    body = str(e.content) if hasattr(e, "content") else str(e)
    return "insufficientPermissions" in body or "Insufficient Permission" in body


def _is_quota_exceeded_error(e: HttpError) -> bool:
    """Check if an HttpError is a quota exceeded error."""
    if e.resp.status != 403:
        return False
    body = str(e.content) if hasattr(e, "content") else str(e)
    return "quotaExceeded" in body or "quota" in body.lower()


def _format_quota_error(e: HttpError) -> str:
    """Format a quota exceeded error into a user-friendly message."""
    state = None
    body = str(e.content) if hasattr(e, "content") else str(e)

    if "quotaExceeded" in body:
        return (
            "YouTube API quota exceeded!\n\n"
            "The request cannot be completed because you have exceeded your daily quota.\n\n"
            "Possible solutions:\n"
            "  1. Wait until the quota resets (typically midnight PT)\n"
            "  2. Request a quota increase from Google Cloud Console\n"
            "  3. Use batch operations to reduce the number of API calls\n\n"
            "To check your current quota usage, run: youtube setup status"
        )

    return str(e)


def _needs_scope_refresh(e: HttpError) -> bool:
    """Check if the error indicates the token needs re-authentication with broader scopes."""
    return _is_insufficient_permissions_error(e)


class YouTubeClient:
    """YouTube API client with quota tracking, error handling, and auto-scope refresh."""

    def __init__(
        self,
        api_client: Resource,
        channel_id: Optional[str] = None,
        quota_limit: int = 10000,
        auth=None,
    ):
        self.youtube = api_client
        self.channel_id = channel_id
        self.quota = QuotaTracker(limit=quota_limit)
        self._analytics: Optional[Resource] = None
        self._auth = auth  # YouTubeOAuth instance for auto-reauth

    def _track_quota(self, units: int) -> None:
        """Track quota usage."""
        self.quota.track(units)

    def _refresh_auth_and_rebuild(self) -> None:
        """Force re-auth with full scopes and rebuild the API client."""
        if self._auth is None:
            raise RuntimeError(
                "No auth object available for re-authentication. "
                "Pass auth=YouTubeOAuth(...) when creating YouTubeClient "
                "or run 'youtube setup refresh'."
            )
        logger.info("auto_refreshing_auth", reason="insufficient_permissions")
        from common.youtube.auth import SCOPE_FULL

        self._auth.refresh_auth(scopes=[SCOPE_FULL])
        # Rebuild the YouTube API client with new credentials
        self.youtube = self._auth.get_client(scopes=[SCOPE_FULL])
        logger.info("auth_refreshed_and_client_rebuilt")

    def _with_scope_retry(self, fn: Callable[[], Any]) -> Any:
        """Execute fn, retrying once with fresh auth on insufficientPermissions."""
        try:
            return fn()
        except HttpError as e:
            if _needs_scope_refresh(e):
                self._refresh_auth_and_rebuild()
                return fn()  # retry once
            raise

    def _handle_quota_error(self, e: HttpError, operation: str) -> None:
        """Handle quota exceeded errors with a user-friendly message."""
        if _is_quota_exceeded_error(e):
            raise click.ClickException(_format_quota_error(e))
        logger.error("api_error", operation=operation, error=str(e))

    def get_quota_usage(self) -> dict[str, Any]:
        """Get current quota usage information."""
        state = self.quota.get_state()
        return {
            "usage": state.usage,
            "limit": state.limit,
            "usage_percentage": state.usage_percentage,
            "remaining_percentage": state.remaining_percentage,
        }

    def reset_quota(self) -> None:
        """Reset quota counter."""
        self.quota.reset()

    def get_channel_info(self, channel_id: str) -> Optional[ChannelInfo]:
        """Get channel information. Use 'mine' to get authenticated user's channel."""
        try:
            if channel_id == "mine":
                request = self.youtube.channels().list(
                    part="snippet,statistics",
                    mine=True,
                )
            else:
                request = self.youtube.channels().list(
                    part="snippet,statistics",
                    id=channel_id,
                )
            response = request.execute()
            self._track_quota(1)

            if not response.get("items"):
                logger.warning("channel_not_found", channel_id=channel_id)
                return None

            item = response["items"][0]
            return ChannelInfo.from_api_response(item, item["id"])
        except HttpError as e:
            logger.error("api_error", operation="get_channel_info", error=str(e))
            raise
        except Exception as e:
            logger.error("unexpected_error", operation="get_channel_info", error=str(e))
            raise

    def get_video_details(self, video_id: str) -> Optional[dict[str, Any]]:
        """Get video statistics and details."""
        if not video_id or not video_id.strip():
            logger.error(
                "video_id_empty",
                hint="Provide a valid YouTube video ID or URL. "
                "Example: youtube hot fetch-video https://youtube.com/watch?v=VIDEO_ID",
            )
            raise ValueError(
                "video_id cannot be empty. Provide a YouTube video ID (e.g., '7eEy9yFrVO4') "
                "or full URL (e.g., 'https://youtube.com/watch?v=7eEy9yFrVO4').\n"
                "If you passed a thematic name, use 'youtube hot list <theme>' instead."
            )

        try:
            request = self.youtube.videos().list(
                part="statistics,snippet,contentDetails",
                id=video_id,
            )
            response = request.execute()
            self._track_quota(1)

            if not response.get("items"):
                logger.warning("video_not_found", video_id=video_id)
                return None

            item = response["items"][0]
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})
            return {
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "description": snippet.get("description", ""),
                "duration": content.get("duration", ""),
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
                "channel_id": snippet.get("channelId", ""),
                "channel_title": snippet.get("channelTitle", ""),
            }
        except HttpError as e:
            self._handle_quota_error(e, "get_video_details")
            raise
        except Exception as e:
            logger.error(
                "unexpected_error", operation="get_video_details", error=str(e)
            )
            raise

    def get_comments(
        self,
        video_id: str,
        max_results: int = 20,
        order: str = "relevance",
    ) -> list[Comment]:
        """Get comments for a video."""
        try:

            def _do():
                request = self.youtube.commentThreads().list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=min(max_results, 100),
                    textFormat="plainText",
                    order=order,
                )
                response = request.execute()
                self._track_quota(1)

                comments = []
                for item in response.get("items", []):
                    comments.append(Comment.from_api_response(item, video_id))

                # Fetch video details to populate channel_name, channel_url, view_count
                # We need snippet (for channel info) + statistics (for view count)
                video_request = self.youtube.videos().list(
                    part="snippet,statistics",
                    id=video_id,
                )
                video_response = video_request.execute()
                self._track_quota(1)

                if video_response.get("items"):
                    video_item = video_response["items"][0]
                    snippet = video_item.get("snippet", {})
                    stats = video_item.get("statistics", {})
                    channel_id = snippet.get("channelId", "")
                    channel_title = snippet.get("channelTitle", "")
                    video_title = snippet.get("title", "")
                    channel_url = (
                        f"https://www.youtube.com/channel/{channel_id}"
                        if channel_id
                        else None
                    )
                    view_count = int(stats.get("viewCount", 0))

                    for comment in comments:
                        comment.view_count = view_count
                        comment.channel_name = channel_title
                        comment.channel_url = channel_url
                        comment.video_title = video_title

                logger.info(
                    "comments_retrieved",
                    video_id=video_id,
                    count=len(comments),
                )
                return comments

            return self._with_scope_retry(_do)
        except HttpError as e:
            if e.resp.status == 403 and "commentsDisabled" in str(e):
                logger.warning("comments_disabled", video_id=video_id)
                return []
            logger.error("api_error", operation="get_comments", error=str(e))
            raise
        except Exception as e:
            logger.error("unexpected_error", operation="get_comments", error=str(e))
            raise

    def post_comment_reply(self, comment_id: str, text: str) -> Optional[ReplyResult]:
        """Post a reply to a comment."""
        if not self.channel_id:
            raise ValueError("channel_id required for posting replies")

        try:

            def _do():
                request = self.youtube.comments().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "parentId": comment_id,
                            "textOriginal": text,
                        }
                    },
                )
                response = request.execute()
                self._track_quota(50)

                result = ReplyResult.from_api_response(response)
                logger.info(
                    "reply_posted",
                    comment_id=comment_id,
                    moderation_status=result.moderation_status,
                )
                return result

            return self._with_scope_retry(_do)
        except HttpError as e:
            logger.error("api_error", operation="post_comment_reply", error=str(e))
            raise
        except Exception as e:
            logger.error(
                "unexpected_error", operation="post_comment_reply", error=str(e)
            )
            raise

    def post_comment(self, video_id: str, text: str) -> Optional[CommentResult]:
        """Post a top-level comment on a video."""
        if not self.channel_id:
            raise ValueError("channel_id required for posting comments")

        try:

            def _do():
                request = self.youtube.commentThreads().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "videoId": video_id,
                            "topLevelComment": {
                                "snippet": {
                                    "textOriginal": text,
                                }
                            },
                        }
                    },
                )
                response = request.execute()
                self._track_quota(50)

                snippet = response.get("snippet", {})
                top_level_comment = snippet.get("topLevelComment", {})
                result = CommentResult.from_api_response(top_level_comment, video_id)
                logger.info(
                    "comment_posted",
                    video_id=video_id,
                    comment_id=result.id,
                    moderation_status=result.moderation_status,
                )
                return result

            return self._with_scope_retry(_do)
        except HttpError as e:
            logger.error("api_error", operation="post_comment", error=str(e))
            raise
        except Exception as e:
            logger.error("unexpected_error", operation="post_comment", error=str(e))
            raise

    def search_videos(
        self,
        query: str,
        max_results: int = 10,
        order: str = "relevance",
        language: str = "en",
        combine_keywords: bool = False,
        language_filter: bool = False,
    ) -> list[Video]:
        """Search for videos on YouTube.

        Args:
            query: Search query string
            max_results: Maximum number of results to return
            order: Sort order (relevance, date, rating, title, viewCount)
            language: Language code for relevance ranking (ISO 639-1, e.g., 'en', 'fr', 'es')
            combine_keywords: If True, replaces spaces with ' | ' for OR logic
            language_filter: If True, strictly filter results to only videos with
                           matching audio language. Requires additional API calls.
        """
        try:
            if combine_keywords:
                modified_query = query.replace(" ", " | ")
            else:
                modified_query = query

            api_max_results = min(max_results * 5, 50)

            if language == "fr" and order != "relevance":
                request = self.youtube.search().list(
                    part="snippet",
                    q=modified_query,
                    maxResults=api_max_results,
                    type="video",
                    order=order,
                    location="46.2276,2.2137",
                    locationRadius="1000km",
                )
            else:
                request = self.youtube.search().list(
                    part="snippet",
                    q=modified_query,
                    maxResults=api_max_results,
                    type="video",
                    relevanceLanguage=language,
                    order=order,
                )

            response = request.execute()
            self._track_quota(100)

            videos = []
            video_ids = []

            for item in response.get("items", []):
                if "videoId" in item.get("id", {}):
                    video_ids.append(item["id"]["videoId"])
                else:
                    logger.debug("item_filtered_no_video_id", item=item)

            if video_ids:
                # Include contentDetails to get language information
                video_details_request = self.youtube.videos().list(
                    part="snippet,statistics,contentDetails",
                    id=",".join(video_ids[:50]),
                )
                video_details_response = video_details_request.execute()
                self._track_quota(1)

                video_details_map = {
                    item["id"]: item for item in video_details_response.get("items", [])
                }

                for item in response.get("items", []):
                    if "videoId" not in item.get("id", {}):
                        continue
                    video_id = item["id"]["videoId"]
                    details = video_details_map.get(video_id)

                    # Apply strict language filter if requested
                    if language_filter and details:
                        snippet = details.get("snippet", {})
                        audio_lang = snippet.get("defaultAudioLanguage", "")
                        default_lang = snippet.get("defaultLanguage", "")

                        # Check if either language matches the requested language
                        if audio_lang != language and default_lang != language:
                            logger.debug(
                                "language_filter_skipped",
                                video_id=video_id,
                                audio_language=audio_lang,
                                default_language=default_lang,
                                requested_language=language,
                            )
                            continue

                    video = Video.from_search_result(item, details)
                    videos.append(video)

            logger.info(
                "search_completed",
                query=query,
                results=len(videos),
                requested=max_results,
                language_filter=language_filter,
            )
            return videos[:max_results]
        except HttpError as e:
            logger.error("api_error", operation="search_videos", error=str(e))
            raise
        except Exception as e:
            logger.error("unexpected_error", operation="search_videos", error=str(e))
            raise

    def get_trending_videos(
        self,
        language: str = "US",
        category_id: int = 0,
        max_results: int = 50,
    ) -> list[Video]:
        """Get trending videos."""
        try:
            request = self.youtube.videos().list(
                part="snippet,statistics",
                chart="mostPopular",
                regionCode=language.upper(),
                videoCategoryId=str(category_id) if category_id else None,
                maxResults=min(max_results, 50),
            )
            response = request.execute()
            self._track_quota(1)

            videos = []
            for item in response.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                video = Video(
                    video_id=item["id"],
                    title=snippet.get("title", "N/A"),
                    description=snippet.get("description", ""),
                    channel_id=snippet.get("channelId", ""),
                    channel_title=snippet.get("channelTitle", ""),
                    view_count=int(stats.get("viewCount", 0)),
                    like_count=int(stats.get("likeCount", 0)),
                    comment_count=int(stats.get("commentCount", 0)),
                    published_at=snippet.get("publishedAt", ""),
                    url=f"https://www.youtube.com/watch?v={item['id']}",
                )
                videos.append(video)

            logger.info("trending_retrieved", count=len(videos))
            return videos
        except HttpError as e:
            logger.error("api_error", operation="get_trending_videos", error=str(e))
            raise
        except Exception as e:
            logger.error(
                "unexpected_error", operation="get_trending_videos", error=str(e)
            )
            raise

    def get_channel_videos(
        self,
        channel_id: str,
        max_results: int = 50,
    ) -> list[Video]:
        """Get all videos from a channel."""
        try:
            videos = []
            next_page_token = None

            while len(videos) < max_results:
                search_response = (
                    self.youtube.search()
                    .list(
                        part="snippet",
                        channelId=channel_id,
                        type="video",
                        order="date",
                        maxResults=min(50, max_results - len(videos)),
                        pageToken=next_page_token,
                    )
                    .execute()
                )
                self._track_quota(100)  # search costs 100 units

                video_ids = [
                    item["id"]["videoId"]
                    for item in search_response.get("items", [])
                    if "videoId" in item.get("id", {})
                ]

                if video_ids:
                    # Get full details including status
                    video_details = (
                        self.youtube.videos()
                        .list(
                            part="contentDetails,snippet,status",
                            id=",".join(video_ids),
                        )
                        .execute()
                    )
                    self._track_quota(1)

                    for item in video_details.get("items", []):
                        video_id = item["id"]
                        snippet = item.get("snippet", {})
                        status = item.get("status", {})
                        content = item.get("contentDetails", {})

                        video = Video(
                            video_id=video_id,
                            title=snippet.get("title", "N/A"),
                            description=snippet.get("description", ""),
                            channel_id=channel_id,
                            channel_title=snippet.get("channelTitle", ""),
                            published_at=snippet.get("publishedAt", ""),
                            url=f"https://www.youtube.com/watch?v={video_id}",
                            duration=content.get("duration", ""),
                            privacy_status=status.get("privacyStatus", "public"),
                        )
                        videos.append(video)

                next_page_token = search_response.get("nextPageToken")
                if not next_page_token:
                    break

            logger.info(
                "channel_videos_retrieved", channel_id=channel_id, count=len(videos)
            )
            return videos[:max_results]
        except HttpError as e:
            logger.error("api_error", operation="get_channel_videos", error=str(e))
            raise
        except Exception as e:
            logger.error(
                "unexpected_error", operation="get_channel_videos", error=str(e)
            )
            raise

    def get_video_infos(self, video_id: str) -> Optional[Video]:
        """Get complete video information."""
        try:
            details = self.get_video_details(video_id)
        except ValueError as e:
            raise click.ClickException(str(e)) from e

        if not details:
            return None

        return Video(
            video_id=video_id,
            title=details.get("title", "N/A"),
            description=details.get("description", ""),
            channel_id=details.get("channel_id", ""),
            channel_title=details.get("channel_title", ""),
            view_count=details.get("view_count", 0),
            like_count=details.get("like_count", 0),
            comment_count=details.get("comment_count", 0),
            published_at=details.get("published_at", ""),
            url=f"https://www.youtube.com/watch?v={video_id}",
        )
