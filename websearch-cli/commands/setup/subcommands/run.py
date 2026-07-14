from __future__ import annotations

import click

from common.core.config import load_tool_config, save_tool_config


def register(plugin_manifests: dict) -> click.Command:
    @click.command("run", help="Interactive wizard that writes websearch defaults.")
    def run_cmd():
        config = load_tool_config("websearch")

        language = click.prompt(
            "Default language (hl)", default=str(config.get("language", "fr"))
        ).strip()
        limit = click.prompt(
            "Default limit (items per provider)",
            default=int(config.get("limit", 10)),
            type=int,
        )
        reddit_id = click.prompt(
            "Reddit client_id (optional, empty to skip)",
            default=str((config.get("reddit") or {}).get("client_id", "")),
        ).strip()
        reddit_secret = click.prompt(
            "Reddit client_secret (optional, empty to skip)",
            default=str((config.get("reddit") or {}).get("client_secret", "")),
            hide_input=True,
        ).strip()

        reddit = dict(config.get("reddit") or {})
        reddit["user_agent"] = reddit.get("user_agent", "fast-market-websearch/1.0")
        if reddit_id:
            reddit["client_id"] = reddit_id
        if reddit_secret:
            reddit["client_secret"] = reddit_secret

        config["language"] = language
        config["limit"] = limit
        config["google_news"] = {
            "hl": language,
            "gl": language.upper(),
        }
        config["reddit"] = reddit
        config.setdefault("hacker_news", {"tags": "story"})

        save_tool_config("websearch", config)
        click.echo("Saved websearch config. Run `websearch setup show` to verify.")

    return run_cmd
