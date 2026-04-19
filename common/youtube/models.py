from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Video(BaseModel):
    video_id: str
    title: str
    description: str = ""
    channel_id: str
    channel_title: str = ""
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    published_at: str
    url: str
    subscriber_count: int = 0
    relevance_score: float = 0.0
    language: str = ""
    days_old: int = 0
    duration: str = ""  # ISO 8601 duration (e.g., "PT5M34S")
    privacy_status: str = "public"  # public, private, unlisted, members

    @classmethod
    def from_search_result(cls, item: dict, details: Optional[dict] = None) -> "Video":
        video_id = item["id"]["videoId"]
        snippet = item["snippet"]
        stats = details.get("statistics", {}) if details else {}
        snippet_details = details.get("snippet", {}) if details else {}
        return cls(
            video_id=video_id,
            title=snippet.get("title", "N/A"),
            description=snippet.get("description", ""),
            channel_id=snippet.get("channelId", ""),
            channel_title=snippet.get("channelTitle", ""),
            view_count=int(stats.get("viewCount", 0)),
            like_count=int(stats.get("likeCount", 0)),
            comment_count=int(stats.get("commentCount", 0)),
            published_at=snippet.get("publishedAt", ""),
            url=f"https://www.youtube.com/watch?v={video_id}",
        )

    @classmethod
    def from_video_list(cls, item: dict) -> "Video":
        video_id = item.get("id", item.get("video_id", ""))
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        return cls(
            video_id=video_id,
            title=snippet.get("title", item.get("title", "N/A")),
            description=snippet.get("description", item.get("description", "")),
            channel_id=snippet.get("channelId", item.get("channel_id", "")),
            channel_title=snippet.get("channelTitle", item.get("channel_title", "")),
            view_count=int(stats.get("viewCount", item.get("view_count", 0))),
            like_count=int(stats.get("likeCount", item.get("like_count", 0))),
            comment_count=int(stats.get("commentCount", item.get("comment_count", 0))),
            published_at=snippet.get("publishedAt", item.get("published_at", "")),
            url=f"https://www.youtube.com/watch?v={video_id}",
            subscriber_count=item.get("subscriber_count", 0),
            relevance_score=item.get("relevance_score", 0.0),
            days_old=item.get("days_old", 0),
        )

    def to_dict(self) -> dict:
        return self.model_dump()


class Comment(BaseModel):
    id: str
    text: str
    author: str
    published_at: str
    video_id: str
    video_title: Optional[str] = None
    like_count: int = 0
    parent_id: Optional[str] = None
    total_reply_count: int = 0
    channel_name: Optional[str] = None
    channel_url: Optional[str] = None
    view_count: int = 0

    @classmethod
    def from_api_response(cls, item: dict, video_id: str) -> "Comment":
        snippet = item["snippet"]
        top_level_comment = snippet.get("topLevelComment", {}).get("snippet", snippet)
        return cls(
            id=item.get("id", ""),
            text=top_level_comment.get(
                "textDisplay", top_level_comment.get("textOriginal", "")
            ),
            author=top_level_comment.get("authorDisplayName", "Unknown"),
            published_at=top_level_comment.get("publishedAt", ""),
            video_id=video_id,
            like_count=int(top_level_comment.get("likeCount", 0)),
            parent_id=snippet.get("parentId"),
            total_reply_count=int(snippet.get("totalReplyCount", 0)),
        )

    def to_dict(self) -> dict:
        return self.model_dump()


class ReplyResult(BaseModel):
    id: str
    parent_id: str
    text: str
    author: str
    published_at: str
    moderation_status: str = "unknown"
    video_id: Optional[str] = None

    @classmethod
    def from_api_response(cls, response: dict) -> "ReplyResult":
        snippet = response.get("snippet", {})
        return cls(
            id=response.get("id", ""),
            parent_id=snippet.get("parentId", ""),
            text=snippet.get("textOriginal", ""),
            author=snippet.get("authorDisplayName", "Unknown"),
            published_at=snippet.get("publishedAt", ""),
            moderation_status=snippet.get("moderationStatus", "unknown"),
            video_id=snippet.get("videoId"),
        )

    def to_dict(self) -> dict:
        return self.model_dump()


class CommentResult(BaseModel):
    id: str
    video_id: str
    text: str
    author: str
    published_at: str
    moderation_status: str = "unknown"

    @classmethod
    def from_api_response(cls, response: dict, video_id: str) -> "CommentResult":
        snippet = response.get("snippet", {})
        return cls(
            id=response.get("id", ""),
            video_id=video_id,
            text=snippet.get("textOriginal", ""),
            author=snippet.get("authorDisplayName", "Unknown"),
            published_at=snippet.get("publishedAt", ""),
            moderation_status=snippet.get("moderationStatus", "unknown"),
        )

    def to_dict(self) -> dict:
        return self.model_dump()


class ChannelInfo(BaseModel):
    channel_id: str
    title: str
    subscriber_count: int = 0
    view_count: int = 0
    video_count: int = 0
    description: str = ""
    custom_url: Optional[str] = None

    @classmethod
    def from_api_response(cls, item: dict, channel_id: str) -> "ChannelInfo":
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        return cls(
            channel_id=channel_id,
            title=snippet.get("title", "Unknown"),
            subscriber_count=int(statistics.get("subscriberCount", 0)),
            view_count=int(statistics.get("viewCount", 0)),
            video_count=int(statistics.get("videoCount", 0)),
            description=snippet.get("description", ""),
            custom_url=snippet.get("customUrl"),
        )

    def to_dict(self) -> dict:
        return self.model_dump()


class QuotaUsage(BaseModel):
    usage: int = 0
    limit: int = 10000
    usage_percentage: float = 0.0
    remaining_percentage: float = 100.0

    def to_dict(self) -> dict:
        return self.model_dump()
