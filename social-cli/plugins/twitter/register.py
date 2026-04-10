from __future__ import annotations

from plugins.base import PluginManifest
from plugins.twitter.plugin import TwitterPlugin

# Commented default config template — provided by the plugin for modularity.
CONFIG_TEMPLATE = """\
# Twitter / X Configuration
# =========================
# Place this file at: ~/.config/social/twitter/config.yaml

# Twitter API v2 bearer token (required)
# Get it from: https://developer.twitter.com/en/portal/dashboard
twitter_bearer_token: ""

# Twitter API v2 API Key (Consumer Key)
twitter_api_key: ""

# Twitter API v2 API Secret (Consumer Secret)
twitter_api_secret: ""

# Twitter API v2 Access Token
twitter_access_token: ""

# Twitter API v2 Access Token Secret
twitter_access_token_secret: ""

# ---- Optional: Twitter API v1.1 (required for media uploads) ----
# Set to true to enable v1.1 for uploading images
twitter_api_v1_enabled: false

# Twitter API v1.1 Consumer Key (can be same as v2)
twitter_api_v1_consumer_key: ""

# Twitter API v1.1 Consumer Secret (can be same as v2)
twitter_api_v1_consumer_secret: ""

# Twitter API v1.1 Access Token
twitter_api_v1_access_token: ""

# Twitter API v1.1 Access Token Secret
twitter_api_v1_access_token_secret: ""
"""


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="twitter",
        source_plugin_class=TwitterPlugin,
        config_template=CONFIG_TEMPLATE,
    )
