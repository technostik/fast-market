#!/usr/bin/env python3
"""Get the authenticated user's YouTube channel ID."""

import sys
from pathlib import Path

# Add corpus-cli to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.core.config import load_config
from common.youtube.client import YouTubeClient
from common.youtube.auth import YouTubeOAuth


def main():
    config = load_config()
    yt_cfg = config.get("youtube", {})

    # Get authenticated client
    client_secret = yt_cfg.get("client_secret_path")
    oauth = YouTubeOAuth(client_secret_path=client_secret)
    api = oauth.get_client()
    client = YouTubeClient(api, auth=oauth)

    # Get authenticated user's channel
    try:
        channel_info = client.get_channel_info("mine")
        if channel_info:
            print(f"Your YouTube channel ID: {channel_info.channel_id}")
            print(f"Channel title: {channel_info.title}")
            print(
                f"Compare this with the channel_id in your config: {yt_cfg.get('channel_id', 'NOT SET')}"
            )
        else:
            print("Could not get channel info. Check OAuth setup.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
