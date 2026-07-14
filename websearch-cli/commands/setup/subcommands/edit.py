from __future__ import annotations

import click

from common.cli.helpers import open_editor
from common.core.paths import get_tool_config_path


def register(plugin_manifests: dict) -> click.Command:
    @click.command("edit", help="Open the websearch config file in your editor.")
    def edit_cmd():
        path = get_tool_config_path("websearch")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
        open_editor(path)

    return edit_cmd
