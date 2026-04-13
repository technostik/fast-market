from __future__ import annotations

from pathlib import Path
from typing import Optional

from common import structlog
from common.youtube.auth import YouTubeOAuth, get_client_secret_path
from common.core.config import load_tool_config, load_youtube_config
from common.youtube import YouTubeClient

logger = structlog.get_logger(__name__)


def build_youtube_client(config: Optional[dict] = None) -> YouTubeClient:
    """Build authenticated YouTube client from config."""
    if config is None:
        config = load_tool_config("youtube")

    youtube_config = config.get("youtube", {})
    client_secret = youtube_config.get("client_secret_path")
    channel_id = youtube_config.get("channel_id")
    quota_limit = youtube_config.get("quota_limit")

    # Fall back to common youtube config if values are empty
    if not channel_id or not client_secret or quota_limit is None:
        common_cfg = load_youtube_config()
        if not channel_id:
            channel_id = common_cfg.get("channel_id")
        if not client_secret:
            client_secret = common_cfg.get("client_secret_path")
        if quota_limit is None:
            quota_limit = common_cfg.get("quota_limit", 10000)

    if not client_secret:
        client_secret = get_client_secret_path()
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

    logger.info("youtube_client_built", channel_id=channel_id, quota_limit=quota_limit)
    return YouTubeClient(api_client, channel_id=channel_id, quota_limit=quota_limit, auth=auth)
