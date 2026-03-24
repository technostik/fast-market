from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("setconfig")
    @click.pass_context
    def setconfig_cmd(ctx, **kwargs):
        """Interactively edit config.yaml settings.

        \b
        Lets you add or remove obsidian.exclude_dirs entries and other
        config values without editing config.yaml by hand.
        """
        _configure_logging(ctx.obj["verbose"])
        import yaml as _yaml
        from pathlib import Path as _Path

        cfg_path = _Path("config.yaml")
        if not cfg_path.exists():
            raise click.ClickException("config.yaml not found — run 'corpus setup' first")

        config = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

        click.echo("=== corpus setconfig ===")
        click.echo("Press Enter to keep current value. Type a new value to change it.")
        click.echo("")

        # --- obsidian.exclude_dirs ---
        ob_cfg = config.setdefault("obsidian", {})
        current_excludes: list[str] = list(ob_cfg.get("exclude_dirs") or [])
        built_in = {".obsidian", ".trash", ".git"}
        click.echo(f"obsidian.exclude_dirs (built-in: {sorted(built_in)})")
        click.echo(f"  current extra excludes: {current_excludes or '(none)'}")
        click.echo("  Enter comma-separated directory names to EXCLUDE (e.g. Templates,Archive).")
        click.echo("  Enter '-' to clear all extra excludes.")
        raw = click.prompt("  exclude_dirs", default=",".join(current_excludes) if current_excludes else "", show_default=False).strip()
        if raw == "-":
            ob_cfg["exclude_dirs"] = []
            click.echo("  → cleared")
        elif raw:
            new_excludes = [d.strip() for d in raw.split(",") if d.strip()]
            ob_cfg["exclude_dirs"] = new_excludes
            click.echo(f"  → {new_excludes}")
        else:
            click.echo("  → unchanged")

        click.echo("")

        # --- embed_batch_size ---
        current_batch = config.get("embed_batch_size", 32)
        raw = click.prompt(f"embed_batch_size", default=str(current_batch)).strip()
        try:
            config["embed_batch_size"] = int(raw)
        except ValueError:
            click.echo("  invalid integer, keeping current value")

        click.echo("")

        # --- youtube.index_non_public ---
        yt_cfg = config.setdefault("youtube", {})
        current_inp = bool(yt_cfg.get("index_non_public", False))
        raw = click.prompt(f"youtube.index_non_public (true/false)", default=str(current_inp).lower()).strip().lower()
        yt_cfg["index_non_public"] = raw in ("true", "1", "yes")

        click.echo("")
        cfg_path.write_text(_yaml.dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        click.echo(f"Saved to {cfg_path}")

        # Show the resulting exclude list (built-in + configured)
        all_excludes = sorted(built_in | set(ob_cfg.get("exclude_dirs") or []))
        click.echo(f"Effective obsidian exclude_dirs: {all_excludes}")

    return CommandManifest(name="setconfig", click_command=setconfig_cmd)
