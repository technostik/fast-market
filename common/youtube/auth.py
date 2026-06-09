from __future__ import annotations

import subprocess
import time
import webbrowser
from pathlib import Path

from common import structlog
from common.auth.base import AuthProvider

logger = structlog.get_logger(__name__)

# Scopes ordered from least to most permissive
SCOPE_READONLY = "https://www.googleapis.com/auth/youtube.readonly"
SCOPE_FULL = "https://www.googleapis.com/auth/youtube.force-ssl"

DEFAULT_SCOPES = [SCOPE_FULL]

HEADLESS_AUTH_TIMEOUT = 300


def get_youtube_auth_dir() -> Path:
    """Get the shared YouTube auth directory (~/.config/fast-market/common/youtube/)."""
    return Path.home() / ".config" / "fast-market" / "common" / "youtube"


def get_client_secret_path() -> str:
    """Get the default client_secret.json path."""
    return str(get_youtube_auth_dir() / "client_secret.json")


class YouTubeOAuth(AuthProvider):
    """Shared YouTube OAuth client builder for fast-market tools."""

    def __init__(self, client_secret_path: str | None = None):
        if client_secret_path is None:
            client_secret_path = get_client_secret_path()
        self.client_secret_path = client_secret_path
        self.token_path = Path(client_secret_path).expanduser().parent / "token.json"

    def _headless_oauth_flow(self, flow):
        """Run OAuth without a browser: alert with URL, wait up to 5 min for token."""
        auth_url, _ = flow.authorization_url(prompt="consent")
        logger.error(
            "oauth_no_browser",
            auth_url=auth_url,
            token_path=str(self.token_path),
        )
        subprocess.run(
            [
                "message",
                "alert",
                "🔑 YouTube OAuth required — no browser available.\n"
                f"1. Open this URL in any browser: {auth_url}\n"
                f"2. Authenticate and grant permissions\n"
                f"3. Copy the generated token.json to: {self.token_path}\n"
                "The system will wait up to 5 minutes.",
            ]
        )
        deadline = time.time() + HEADLESS_AUTH_TIMEOUT
        while time.time() < deadline:
            if self.token_path.exists():
                from google.oauth2.credentials import Credentials
                logger.info("oauth_token_detected", path=str(self.token_path))
                return Credentials.from_authorized_user_file(str(self.token_path))
            time.sleep(5)
        raise RuntimeError(
            f"YouTube OAuth token not provided within "
            f"{HEADLESS_AUTH_TIMEOUT // 60} minutes.\n"
            f"Auth URL: {auth_url}\n"
            f"Expected token path: {self.token_path}"
        )

    def get_client(self, scopes: list[str] | None = None):
        """Return authenticated YouTube API client.

        Args:
            scopes: OAuth scopes to request. Defaults to [SCOPE_FULL] for full access.
        """
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise RuntimeError(
                "pip install google-api-python-client google-auth-oauthlib"
            ) from exc

        if scopes is None:
            scopes = DEFAULT_SCOPES

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path))

        if creds and creds.valid:
            token_scopes = set(getattr(creds, "scopes", []) or [])
            required = set(scopes)
            if not required.issubset(token_scopes):
                logger.info(
                    "oauth_scope_insufficient",
                    current_scopes=sorted(token_scopes),
                    required_scopes=sorted(required),
                )
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(Path(self.client_secret_path).expanduser()),
                    scopes=scopes,
                )
                try:
                    creds = flow.run_local_server(port=0, prompt="consent")
                except webbrowser.Error:
                    creds = self._headless_oauth_flow(flow)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
            logger.info("oauth_token_saved", path=str(self.token_path))

        return build("youtube", "v3", credentials=creds)

    def refresh_auth(self, scopes: list[str] | None = None) -> None:
        """Force re-authentication, deleting any existing token.

        Args:
            scopes: OAuth scopes to request. Defaults to [SCOPE_FULL].
        """
        if scopes is None:
            scopes = DEFAULT_SCOPES

        if self.token_path.exists():
            self.token_path.unlink()
            logger.info("oauth_token_deleted", path=str(self.token_path))

        self.get_client(scopes=scopes)
        logger.info("oauth_refresh_complete", scopes=scopes)


__all__ = ["YouTubeOAuth", "SCOPE_READONLY", "SCOPE_FULL", "DEFAULT_SCOPES", "get_youtube_auth_dir", "get_client_secret_path"]
