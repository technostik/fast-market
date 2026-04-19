from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta
from pathlib import Path

from common import structlog
from common.youtube.auth import YouTubeOAuth, get_youtube_auth_dir

logger = structlog.get_logger(__name__)


class DiagnosticResult:
    def __init__(
        self,
        test_name: str,
        status: str,
        message: str,
        details: dict | None = None,
    ):
        self.test_name = test_name
        self.status = status
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "test": self.test_name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


def run_all_diagnostics(config: dict) -> list[DiagnosticResult]:
    """Run all diagnostic tests for YouTube integration."""
    results = []

    results.append(check_oauth_token(config))
    results.append(check_network_connectivity())
    results.append(check_api_credentials(config))
    results.append(check_quota_usage(config))

    return results


def check_oauth_token(config: dict) -> DiagnosticResult:
    """Check OAuth token status."""
    token_path = get_youtube_auth_dir() / "token.json"

    if not token_path.exists():
        return DiagnosticResult(
            "oauth_token",
            "error",
            "OAuth token not found",
            {"token_path": str(token_path)},
        )

    try:
        token_data = json.loads(token_path.read_text(encoding="utf-8"))
    except Exception as e:
        return DiagnosticResult(
            "oauth_token",
            "error",
            f"Failed to read token: {e}",
            {"token_path": str(token_path)},
        )

    details = {
        "token_path": str(token_path),
        "has_refresh_token": bool(token_data.get("refresh_token")),
        "has_access_token": bool(token_data.get("access_token")),
    }

    expiry = token_data.get("token_expiry")
    if expiry:
        details["token_expiry"] = expiry
        try:
            expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if expiry_dt < datetime.now(expire_dt.tzinfo):
                details["expired"] = True
                return DiagnosticResult(
                    "oauth_token",
                    "error",
                    "OAuth token expired",
                    details,
                )
        except Exception:
            pass

    if token_data.get("invalid"):
        details["invalid"] = True
        return DiagnosticResult(
            "oauth_token",
            "error",
            "OAuth token marked as invalid",
            details,
        )

    return DiagnosticResult(
        "oauth_token",
        "ok",
        "OAuth token exists and appears valid",
        details,
    )


def check_network_connectivity() -> DiagnosticResult:
    """Check basic network connectivity to YouTube."""
    test_hosts = [
        ("youtube.com", 443),
        ("www.youtube.com", 443),
        ("accounts.google.com", 443),
    ]

    results = []
    for host, port in test_hosts:
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
            results.append(f"{host}:ok")
        except Exception as e:
            results.append(f"{host}:failed ({e})")
            return DiagnosticResult(
                "network",
                "error",
                f"Cannot connect to {host}",
                {"connectivity": results},
            )

    return DiagnosticResult(
        "network",
        "ok",
        "Successfully connected to YouTube",
        {"connectivity": results},
    )


def check_api_credentials(config: dict) -> DiagnosticResult:
    """Check API credentials and OAuth setup."""
    yt_config = config.get("youtube", {})
    client_secret_path = yt_config.get("client_secret_path")

    if not client_secret_path:
        default_path = get_youtube_auth_dir() / "client_secret.json"
        client_secret_path = str(default_path)

    client_secret_file = Path(client_secret_path).expanduser()

    if not client_secret_file.exists():
        return DiagnosticResult(
            "api_credentials",
            "error",
            f"client_secret.json not found",
            {"client_secret_path": str(client_secret_file)},
        )

    try:
        client_data = json.loads(client_secret_file.read_text(encoding="utf-8"))

        installed = client_data.get("installed", {}) or client_data.get("web", {})
        if not installed:
            return DiagnosticResult(
                "api_credentials",
                "error",
                "No 'installed' or 'web' block in client_secret.json",
                {},
            )

        has_client_id = bool(installed.get("client_id"))
        has_client_secret = bool(installed.get("client_secret"))

        if not has_client_id:
            return DiagnosticResult(
                "api_credentials",
                "error",
                "Missing client_id in client_secret.json",
                {},
            )

        if not has_client_secret:
            return DiagnosticResult(
                "api_credentials",
                "error",
                "Missing client_secret in client_secret.json",
                {},
            )

        details = {
            "client_secret_path": str(client_secret_file),
            "has_client_id": has_client_id,
            "has_client_secret": has_client_secret,
            "client_id_first_chars": installed.get("client_id", "")[:20] + "...",
        }
        return DiagnosticResult(
            "api_credentials",
            "ok",
            "API credentials present",
            details,
        )

    except json.JSONDecodeError as e:
        return DiagnosticResult(
            "api_credentials",
            "error",
            f"Invalid JSON in client_secret.json: {e}",
            {"client_secret_path": str(client_secret_file)},
        )
    except Exception as e:
        return DiagnosticResult(
            "api_credentials",
            "error",
            f"Failed to check credentials: {e}",
            {"client_secret_path": str(client_secret_file)},
        )


def check_quota_usage(config: dict) -> DiagnosticResult:
    """Check if quota has been exhausted (experimental)."""
    oauth = YouTubeOAuth()
    token_path = oauth.token_path

    if not token_path.exists():
        return DiagnosticResult(
            "quota",
            "warning",
            "No token file to check quota",
            {},
        )

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(str(token_path))

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                return DiagnosticResult(
                    "quota",
                    "ok",
                    "Token was expired, refreshed successfully",
                    {"token_refreshed": True},
                )
            return DiagnosticResult(
                "quota",
                "error",
                "Token invalid and cannot be refreshed",
                {"token_valid": creds.valid},
            )

        return DiagnosticResult(
            "quota",
            "ok",
            "Token valid",
            {"token_valid": creds.valid},
        )

    except Exception as e:
        error_str = str(e).lower()
        if "quota" in error_str or "exceeded" in error_str:
            return DiagnosticResult(
                "quota",
                "error",
                f"Quota exceeded: {e}",
                {},
            )
        if "invalid" in error_str or "unauthorized" in error_str:
            return DiagnosticResult(
                "quota",
                "error",
                f"Token invalid: {e}",
                {},
            )
        return DiagnosticResult(
            "quota",
            "warning",
            f"Could not check quota: {e}",
            {},
        )


def test_rss_feed(config: dict) -> DiagnosticResult:
    """Test RSS feed fallback."""
    from common.youtube.transport import RSSPlaylistTransport

    yt_config = config.get("youtube", {})
    channel_id = yt_config.get("channel_id")

    if not channel_id:
        return DiagnosticResult(
            "rss_feed",
            "error",
            "No channel_id in config",
            {},
        )

    try:
        transport = RSSPlaylistTransport()
        feed_url = transport.get_uploads_playlist(channel_id)
        videos = []
        for page in transport.iter_playlist_pages(feed_url):
            videos.extend(page)
            if len(videos) >= 5:
                break

        if videos:
            return DiagnosticResult(
                "rss_feed",
                "ok",
                f"RSS feed working, found {len(videos)} videos",
                {"videos_found": len(videos), "feed_url": feed_url},
            )
        else:
            return DiagnosticResult(
                "rss_feed",
                "warning",
                "RSS feed returned no videos",
                {},
            )

    except Exception as e:
        return DiagnosticResult(
            "rss_feed",
            "error",
            f"RSS feed failed: {e}",
            {},
        )


def test_api_client(config: dict) -> DiagnosticResult:
    """Test YouTube API client directly."""
    from googleapiclient.errors import HttpError

    oauth = YouTubeOAuth()

    try:
        client = oauth.get_client()
        channel_id = config.get("youtube", {}).get("channel_id")

        if not channel_id:
            return DiagnosticResult(
                "api_client",
                "error",
                "No channel_id in config",
                {},
            )

        from common.youtube.client import YouTubeClient

        yt_client = YouTubeClient(client, channel_id=channel_id, auth=oauth)
        channel_info = yt_client.get_channel_info(channel_id)

        if channel_info:
            return DiagnosticResult(
                "api_client",
                "ok",
                f"API client working, channel: {channel_info.title}",
                {
                    "channel_title": channel_info.title,
                    "video_count": channel_info.video_count,
                },
            )
        else:
            return DiagnosticResult(
                "api_client",
                "warning",
                "API client connected but no channel info returned",
                {},
            )

    except HttpError as e:
        if e.resp.status == 403 and "quota" in str(e).lower():
            return DiagnosticResult(
                "api_client",
                "error",
                f"API quota exceeded (403): {e}",
                {"status_code": e.resp.status},
            )
        if e.resp.status == 401:
            return DiagnosticResult(
                "api_client",
                "error",
                f"API authentication failed (401): {e}",
                {"status_code": e.resp.status},
            )
        return DiagnosticResult(
            "api_client",
            "error",
            f"API HTTP error: {e}",
            {"status_code": e.resp.status},
        )
    except Exception as e:
        return DiagnosticResult(
            "api_client",
            "error",
            f"API test failed: {e}",
            {},
        )