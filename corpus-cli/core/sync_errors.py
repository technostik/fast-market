from __future__ import annotations


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
    permanent = False


class NetworkError(SyncError):
    permanent = False
