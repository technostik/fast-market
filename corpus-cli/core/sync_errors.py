from __future__ import annotations

from datetime import datetime, timedelta, timezone


class SyncError(Exception):
    """Base sync error with retry policy."""

    permanent: bool = False


class TranscriptUnavailableError(SyncError):
    permanent = True


class MembershipOnlyError(SyncError):
    permanent = True


class VideoBlockedError(SyncError):
    """IP blocked by YouTube - retryable but can be grouped separately."""

    permanent = False


class APIRateLimitError(SyncError):
    """YouTube API quota/rate limit exceeded — transient, retry after reset."""

    permanent = False

    def __init__(
        self, message: str, retry_after_seconds: int | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.quota_reset_at: str | None = None
        if retry_after_seconds is not None:
            self.quota_reset_at = (
                datetime.now(timezone.utc) + timedelta(seconds=retry_after_seconds)
            ).isoformat()


class MissingInputFieldError(SyncError):
    """An operation requires an input field that is missing/undeclared."""

    permanent = True


class NetworkError(SyncError):
    permanent = False


class BotDetectionError(SyncError):
    """YouTube challenged the IP for bot behavior (yt-dlp: "Sign in to confirm
    you're not a bot"). Permanent until cookies are provided; enrichment must
    pause immediately instead of hammering the extractor."""

    permanent = True
