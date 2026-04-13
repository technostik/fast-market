from __future__ import annotations

import click

from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> click.Command:
    @click.command(
        "edit",
        help="Open the corpus config and shared youtube config in your default editor.",
    )
    @click.option("--youtube", "-y", is_flag=True, help="Only edit shared youtube config")
    @click.pass_context
    def edit_cmd(ctx, youtube, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        from common.core.paths import get_tool_config_path, get_youtube_config_path
        from common.cli.helpers import open_editor

        yt_cfg_path = get_youtube_config_path()
        cfg_path = get_tool_config_path("corpus")

        if youtube:
            # Only edit shared youtube config
            yt_cfg_path.parent.mkdir(parents=True, exist_ok=True)
            if not yt_cfg_path.exists():
                yt_cfg_path.write_text("# Shared YouTube configuration\nchannel_id: \"\"\n# client_secret_path: ~/.config/fast-market/common/youtube/client_secret.json\nquota_limit: 10000\n")
            click.echo(f"Opening shared youtube config: {yt_cfg_path}")
            open_editor(yt_cfg_path)
        else:
            # Edit both: corpus first, then youtube
            if not cfg_path.exists():
                raise click.ClickException(
                    f"Config file not found at {cfg_path} — run 'corpus setup run' first"
                )
            click.echo(f"Opening corpus config: {cfg_path}")
            open_editor(cfg_path)
            click.echo("")
            click.echo(f"Opening shared youtube config: {yt_cfg_path}")
            yt_cfg_path.parent.mkdir(parents=True, exist_ok=True)
            if not yt_cfg_path.exists():
                yt_cfg_path.write_text("# Shared YouTube configuration\nchannel_id: \"\"\n# client_secret_path: ~/.config/fast-market/common/youtube/client_secret.json\nquota_limit: 10000\n")
            open_editor(yt_cfg_path)

    return edit_cmd
