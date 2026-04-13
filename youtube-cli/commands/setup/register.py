from __future__ import annotations

import shutil
from pathlib import Path

import click

from commands.base import CommandManifest
from common.core.paths import get_tool_config, get_youtube_config_path
from common.core.config import load_youtube_config, save_youtube_config
from common.auth.youtube import YouTubeOAuth, SCOPE_FULL


def _ask(prompt: str, default: str = "") -> str:
    if default:
        prompt = f"{prompt} [{default}]"
    value = input(f"{prompt}: ").strip()
    return value if value else default


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("setup", invoke_without_command=True)
    @click.option("--show", "-s", is_flag=True, help="Display current configuration")
    @click.option("--locate", "-l", is_flag=True, help="Show config file path")
    @click.option("--wizard", "-w", is_flag=True, help="Interactive setup wizard")
    @click.option("--reset", "-R", is_flag=True, help="Reset config to defaults (backs up existing)")
    @click.pass_context
    def setup_group(ctx, show, locate, wizard, reset):
        """Setup and manage youtube-agent configuration.

        When called with no subcommand, acts as 'setup run' for backward compatibility.
        Use 'setup refresh' to re-authenticate with full API access.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(setup_cmd, show=show, locate=locate, wizard=wizard, reset=reset)

    @setup_group.command("run")
    @click.option("--show", "-s", is_flag=True, help="Display current configuration")
    @click.option("--locate", "-l", is_flag=True, help="Show config file path")
    @click.option("--wizard", "-w", is_flag=True, help="Interactive setup wizard")
    @click.option("--reset", "-R", is_flag=True, help="Reset config to defaults (backs up existing)")
    def setup_cmd(show, locate, wizard, reset, **kwargs):
        """Setup and show youtube-agent configuration."""

        cfg_path = get_tool_config("youtube")

        if locate:
            click.echo(f"Shared youtube config: {get_youtube_config_path()}")
            if get_youtube_config_path().exists():
                click.echo("  Status: exists")
            else:
                click.echo("  Status: does not exist (use --wizard to create)")

            click.echo(f"Tool config (legacy): {cfg_path}")
            if cfg_path.exists():
                click.echo("  Status: exists")
            else:
                click.echo("  Status: does not exist")

            secret_path = get_youtube_config_path().parent / "client_secret.json"
            click.echo(f"Client secret: {secret_path}")
            if secret_path.exists():
                click.echo("  Status: exists")
            else:
                click.echo("  Status: does not exist")

            token_path = get_youtube_config_path().parent / "token.json"
            click.echo(f"OAuth token: {token_path}")
            if token_path.exists():
                click.echo("  Status: exists (authenticated)")
            else:
                click.echo(
                    "  Status: does not exist (run a command to authenticate)"
                )

        elif show:
            yt_cfg_path = get_youtube_config_path()
            if yt_cfg_path.exists():
                click.echo(f"# Shared youtube configuration ({yt_cfg_path}):")
                click.echo(yt_cfg_path.read_text())
            else:
                click.echo("No shared youtube configuration found. Use --wizard to create.")

            if cfg_path.exists():
                click.echo(f"\n# Tool config (legacy) ({cfg_path}):")
                click.echo(cfg_path.read_text())

        elif wizard:
            yt_cfg_path = get_youtube_config_path()
            existing = load_youtube_config()

            click.echo("=== YouTube Setup Wizard ===")
            click.echo("Press Enter to keep current value. Type a new value to change it.")
            click.echo("")

            # channel_id
            current_channel = existing.get("channel_id", "")
            click.echo("youtube.channel_id (shared across all tools)")
            click.echo(f"  current: {current_channel or '(not set)'}")
            channel_id = _ask("  channel_id", default=current_channel)
            if channel_id and channel_id != current_channel:
                click.echo(f"  → {channel_id}")
            elif not channel_id:
                click.echo("  → unchanged (empty)")
            else:
                click.echo("  → unchanged")

            click.echo("")

            # client_secret_path
            current_secret = existing.get("client_secret_path", str(get_youtube_config_path().parent / "client_secret.json"))
            click.echo("youtube.client_secret_path")
            click.echo(f"  current: {current_secret or '(not set)'}")
            client_secret = _ask("  client_secret_path", default=current_secret)
            if client_secret:
                secret_p = Path(client_secret).expanduser()
                if not secret_p.exists():
                    click.echo(f"  Warning: file not found: {secret_p}")
                if client_secret != current_secret:
                    click.echo(f"  → {client_secret}")
                else:
                    click.echo("  → unchanged")
            else:
                click.echo("  → unchanged")

            click.echo("")

            # quota_limit
            current_quota = existing.get("quota_limit", 10000)
            click.echo("youtube.quota_limit")
            click.echo(f"  current: {current_quota}")
            raw = _ask("  quota_limit", default=str(current_quota))
            try:
                quota_limit = int(raw)
                if quota_limit != current_quota:
                    click.echo(f"  → {quota_limit}")
                else:
                    click.echo("  → unchanged")
            except ValueError:
                quota_limit = current_quota
                click.echo("  invalid integer, keeping current value")

            click.echo("")

            # Save
            new_yt_cfg = {}
            if channel_id:
                new_yt_cfg["channel_id"] = channel_id
            if client_secret:
                new_yt_cfg["client_secret_path"] = client_secret
            new_yt_cfg["quota_limit"] = quota_limit

            save_youtube_config(new_yt_cfg)
            click.echo(f"Saved shared youtube config to {yt_cfg_path}")
            click.echo("")
            click.echo("Next steps:")
            click.echo("  1. Ensure client_secret.json exists at the configured path")
            click.echo("  2. Run 'youtube search test' to authenticate")

        elif reset:
            yt_cfg_path = get_youtube_config_path()
            if yt_cfg_path.exists():
                backup_path = yt_cfg_path.with_name("config.yaml.bak")
                shutil.copy2(str(yt_cfg_path), str(backup_path))
                click.echo(f"Backed up existing shared config to {backup_path}")
            yt_cfg_path.parent.mkdir(parents=True, exist_ok=True)
            yt_cfg_path.write_text("# YouTube shared configuration\nchannel_id: \"\"\nquota_limit: 10000\n# client_secret_path: ~/.config/fast-market/common/youtube/client_secret.json\n")
            click.echo(f"Reset shared configuration to defaults at {yt_cfg_path}")

        else:
            click.echo("Usage: youtube setup [OPTIONS]")
            click.echo("")
            click.echo("Options:")
            click.echo("  run         Run a specific setup action")
            click.echo("  --locate    Show config file locations")
            click.echo("  --show      Display current configuration")
            click.echo("  --wizard    Interactive setup wizard")
            click.echo("  refresh     Re-authenticate with full API access")
            click.echo("")
            click.echo("First time setup:")
            click.echo("  1. youtube setup --wizard")
            click.echo("  2. Ensure client_secret.json exists at the configured path")
            click.echo("  3. Run 'youtube search test' to authenticate")

    @setup_group.command("refresh")
    def refresh_auth_cmd(**kwargs):
        """Re-authenticate with full API access (youtube.force-ssl scope).

        Use this when you get 'insufficientPermissions' errors.
        This deletes the existing token and opens the browser for re-authentication.
        """
        yt_cfg = load_youtube_config()
        client_secret = yt_cfg.get("client_secret_path")

        if client_secret:
            client_secret = str(Path(client_secret).expanduser())
        else:
            from common.auth.youtube import get_client_secret_path
            client_secret = get_client_secret_path()

        secret_path = Path(client_secret)
        if not secret_path.exists():
            click.echo(f"Error: client_secret.json not found at {secret_path}")
            click.echo("Run 'youtube setup --wizard' to configure it first.")
            raise SystemExit(1)

        click.echo("=== YouTube Auth Refresh ===")
        click.echo(f"Client secret: {secret_path}")
        click.echo("")
        click.echo("This will delete your existing token and re-authenticate.")
        click.echo("The browser will open. Grant all requested permissions.")
        click.echo("")

        auth = YouTubeOAuth(client_secret)
        auth.refresh_auth(scopes=[SCOPE_FULL])

        click.echo("")
        click.echo("Authentication refreshed successfully.")
        click.echo("You now have full API access (youtube.force-ssl scope).")

    return CommandManifest(
        name="setup",
        click_command=setup_group,
    )
