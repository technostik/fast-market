from __future__ import annotations

from plugins.base import PluginManifest
from plugins.linkedin.plugin import LinkedinPlugin

CONFIG_TEMPLATE = """\
# LinkedIn Configuration
# =====================
# Place this file at: ~/.config/social/linkedin/config.yaml

# LinkedIn OAuth 2.0 Client ID
# Get it from: https://developer.linkedin.com/
linkedin_client_id: ""

# LinkedIn OAuth 2.0 Client Secret
linkedin_client_secret: ""

# LinkedIn Access Token (OAuth 2.0 Bearer)
# You can obtain this via the OAuth flow or use a personal access token
linkedin_access_token: ""

# ---- Optional ----
# Redirect URI for OAuth flow (default shown)
# linkedin_redirect_uri: "https://your-app.com/callback"

# API version to use (default: 202504, latest: 202507)
# linkedin_api_version: "202507"
"""


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="linkedin",
        source_plugin_class=LinkedinPlugin,
        config_template=CONFIG_TEMPLATE,
    )
