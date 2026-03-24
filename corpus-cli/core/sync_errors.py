from __future__ import annotations


class SyncError(Exception):
    """Base sync error with retry policy."""

    permanent: bool = False


class TranscriptUnavailableError(SyncError):
    permanent = True


class APIRateLimitError(SyncError):
    permanent = False


class NetworkError(SyncError):
    permanent = False
