from __future__ import annotations

from plugins.base import PluginManifest
from plugins.substack.plugin import SubstackPlugin

CONFIG_TEMPLATE = """\
# Substack Configuration
# ======================
# Place this file at: ~/.config/social/substack/config.yaml
#
# Note: Substack has no official public API. This plugin uses Selenium-based
# cookie authentication as a fallback when cookies expire.

# Substack account email
substack_email: ""

# Substack account password
substack_password: ""

# Publication URL (semicolon-separated if multiple)
# Example: "https://yourblog.substack.com"
substack_publication_url: ""
"""


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="substack",
        source_plugin_class=SubstackPlugin,
        config_template=CONFIG_TEMPLATE,
    )
