from __future__ import annotations

from pathlib import Path

from common import structlog

from common.auth.base import AuthProvider

logger = structlog.get_logger(__name__)


class YouTubeOAuth(AuthProvider):
    """Shared YouTube OAuth client builder for fast-market tools."""

    def __init__(self, client_secret_path: str):
        self.client_secret_path = client_secret_path
        self.token_path = Path(client_secret_path).expanduser().parent / "token.json"

    def get_client(self):
        """Return authenticated YouTube API client."""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise RuntimeError(
                "pip install google-api-python-client google-auth-oauthlib"
            ) from exc

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path))

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(Path(self.client_secret_path).expanduser()),
                    scopes=["https://www.googleapis.com/auth/youtube.readonly"],
                )
                creds = flow.run_local_server(port=0)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
            logger.info("oauth_token_saved", path=str(self.token_path))

        return build("youtube", "v3", credentials=creds)
