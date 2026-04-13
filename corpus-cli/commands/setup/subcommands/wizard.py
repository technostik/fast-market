from __future__ import annotations

import click

from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> click.Command:
    @click.command(
        "wizard",
        help="Run the interactive wizard to edit corpus and shared youtube config settings.",
    )
    @click.pass_context
    def wizard_cmd(ctx, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        import yaml as _yaml
        from common.core.paths import get_tool_config_path
        from common.core.config import (
            load_youtube_config,
            save_youtube_config,
        )

        cfg_path = get_tool_config_path("corpus")
        if not cfg_path.exists():
            raise click.ClickException(
                f"Config file not found at {cfg_path} — run 'corpus setup run' first"
            )

        config = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        yt_cfg = load_youtube_config() or {}

        click.echo("=== corpus setup wizard ===")
        click.echo("Press Enter to keep current value. Type a new value to change it.")
        click.echo("")

        # --- youtube.channel_id (shared) ---
        click.echo("--- Shared YouTube Configuration ---")
        current_channel = yt_cfg.get("youtube", {}).get("channel_id", "") or yt_cfg.get("channel_id", "")
        click.echo("youtube.channel_id (shared across all tools)")
        click.echo(f"  current: {current_channel or '(not set)'}")
        raw = click.prompt("  channel_id", default=current_channel, show_default=False).strip()
        if raw and raw != current_channel:
            yt_cfg["channel_id"] = raw
            click.echo(f"  → {raw}")
        elif not raw:
            click.echo("  → unchanged")
        else:
            click.echo("  → unchanged")

        click.echo("")

        # --- obsidian.exclude_dirs ---
        click.echo("--- Corpus Configuration ---")
        ob_cfg = config.setdefault("obsidian", {})
        current_excludes: list[str] = list(ob_cfg.get("exclude_dirs") or [])
        built_in = {".obsidian", ".trash", ".git"}
        click.echo(f"obsidian.exclude_dirs (built-in: {sorted(built_in)})")
        click.echo(f"  current extra excludes: {current_excludes or '(none)'}")
        click.echo(
            "  Enter comma-separated directory names to EXCLUDE (e.g. Templates,Archive)."
        )
        click.echo("  Enter '-' to clear all extra excludes.")
        raw = click.prompt(
            "  exclude_dirs",
            default=",".join(current_excludes) if current_excludes else "",
            show_default=False,
        ).strip()
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
        raw = click.prompt("embed_batch_size", default=str(current_batch)).strip()
        try:
            config["embed_batch_size"] = int(raw)
        except ValueError:
            click.echo("  invalid integer, keeping current value")

        click.echo("")

        # --- youtube.index_non_public (corpus-specific) ---
        yt_corpus = config.setdefault("youtube", {})
        current_inp = bool(yt_corpus.get("index_non_public", False))
        raw = (
            click.prompt(
                "youtube.index_non_public (true/false, corpus-only)",
                default=str(current_inp).lower(),
            )
            .strip()
            .lower()
        )
        yt_corpus["index_non_public"] = raw in ("true", "1", "yes")

        click.echo("")

        # Save: split shared youtube config from corpus-specific config
        save_youtube_config(yt_cfg)
        cfg_path.write_text(
            _yaml.dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        click.echo("Saved youtube config to shared location")
        click.echo(f"Saved corpus config to {cfg_path}")

        # Show the resulting exclude list (built-in + configured)
        all_excludes = sorted(built_in | set(ob_cfg.get("exclude_dirs") or []))
        click.echo(f"Effective obsidian exclude_dirs: {all_excludes}")

    return wizard_cmd
