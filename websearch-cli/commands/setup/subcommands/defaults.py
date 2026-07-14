from __future__ import annotations

import click

from common.core.paths import get_tool_config_path

_DEFAULTS = """\
# websearch configuration
# ---------------------------------------------------------------------------
# Default language used to derive Google News hl/gl codes (e.g. fr, en).
language: fr

# Maximum number of results requested per provider per search.
limit: 10

# Google News (RSS search)
#   hl: language code   gl: geolocation (country) code
google_news:
  hl: fr
  gl: FR

# Reddit (global search)
#   user_agent:           required descriptive User-Agent header
#   client_id/secret:     optional OAuth credentials that raise rate-limit
#                         headroom and help avoid 403 blocks from Reddit
reddit:
  user_agent: "fast-market-websearch/1.0"
  client_id: ""
  client_secret: ""

# Hacker News (Algolia API)
#   tags: result type filter (story, comment, ...)
hacker_news:
  tags: story
"""


def register(plugin_manifests: dict) -> click.Command:
    @click.command(
        "defaults", help="Write a default websearch config file with inline comments."
    )
    def defaults_cmd():
        path = get_tool_config_path("websearch")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULTS, encoding="utf-8")
        click.echo(f"Wrote default config to {path}")

    return defaults_cmd
