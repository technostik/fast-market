from __future__ import annotations

from pathlib import Path
from typing import Optional

from common import structlog
from common.auth.youtube import YouTubeOAuth
from common.core.config import load_tool_config
from common.core.paths import get_tool_config
from common.youtube import YouTubeClient

logger = structlog.get_logger(__name__)


def build_youtube_client(config: Optional[dict] = None) -> YouTubeClient:
    """Build authenticated YouTube client from config."""
    if config is None:
        config = load_tool_config("youtube")

    youtube_config = config.get("youtube", {})
    client_secret = youtube_config.get("client_secret_path")

    if not client_secret:
        tool_cfg = get_tool_config("youtube")
        client_secret = str(tool_cfg.parent / "client_secret.json")
        if not Path(client_secret).exists():
            raise FileNotFoundError(
                f"client_secret.json not found at {client_secret}. "
                "Download from Google Cloud Console."
            )
    else:
        client_secret = str(Path(client_secret).expanduser())

    if not Path(client_secret).exists():
        raise FileNotFoundError(
            f"Client secret not found: {client_secret}. "
            "Download from Google Cloud Console and place in config directory."
        )

    auth = YouTubeOAuth(client_secret)
    api_client = auth.get_client()
    channel_id = youtube_config.get("channel_id")
    quota_limit = youtube_config.get("quota_limit", 10000)

    logger.info("youtube_client_built", channel_id=channel_id, quota_limit=quota_limit)
    return YouTubeClient(api_client, channel_id=channel_id, quota_limit=quota_limit)
