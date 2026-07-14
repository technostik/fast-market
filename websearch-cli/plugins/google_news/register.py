from __future__ import annotations

import click

from plugins.base import PluginManifest
from plugins.google_news.plugin import GoogleNewsPlugin
from commands.completion import LanguageParamType, CountryParamType


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="google_news",
        provider_class=GoogleNewsPlugin,
        cli_options={
            "search": [
                click.Option(
                    ["--hl"],
                    type=LanguageParamType(),
                    default=None,
                    help="Google News language code (e.g. fr). Overrides config/language.",
                ),
                click.Option(
                    ["--gl"],
                    type=CountryParamType(),
                    default=None,
                    help="Google News geolocation (e.g. FR). Overrides config.",
                ),
            ],
        },
    )
