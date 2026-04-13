from __future__ import annotations

from pathlib import Path

import click

from common import structlog

from common.core.paths import (
    get_fastmarket_dir,
    get_tool_cache_dir,
    get_tool_config,
    get_tool_data_dir,
    get_youtube_config_path,
)
from common.core.config import load_youtube_config, save_youtube_config
from common.core.yaml_utils import dump_yaml

logger = structlog.get_logger(__name__)


def _ask(prompt: str) -> str:
    value = input(prompt).strip()
    if not value:
        raise ValueError(f"Value is required for: {prompt}")
    return value


def _ensure_youtube_config() -> None:
    """Ensure shared youtube config has channel_id and client_secret_path."""
    yt_cfg = load_youtube_config()
    if yt_cfg.get("channel_id") and yt_cfg.get("client_secret_path"):
        return

    click.echo("=== Shared YouTube Configuration ===")
    click.echo("These settings are shared across all fast-market tools.")
    click.echo("")

    if not yt_cfg.get("channel_id"):
        channel_id = _ask("YouTube channel_id: ")
        yt_cfg["channel_id"] = channel_id

    if not yt_cfg.get("client_secret_path"):
        client_secret = Path(_ask("YouTube client_secret.json path: "))
        if not client_secret.exists() or not client_secret.is_file():
            raise FileNotFoundError(f"Invalid client secret path: {client_secret}")
        yt_cfg["client_secret_path"] = str(client_secret)

    save_youtube_config(yt_cfg)
    click.echo(f"Saved shared youtube config to {get_youtube_config_path()}")
    click.echo("")


def run_wizard() -> None:

    # Ensure shared youtube config first
    _ensure_youtube_config()

    # Tool-specific prompts
    vault_path = Path(_ask("Obsidian vault path: "))
    whisper_size = _ask("Whisper model size (tiny/base/small): ")

    if not vault_path.exists() or not vault_path.is_dir():
        raise FileNotFoundError(f"Invalid vault path: {vault_path}")

    root_dir = get_fastmarket_dir()
    config_dir = root_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    data_dir = get_tool_data_dir("corpus")
    cache_dir = get_tool_cache_dir("corpus")
    config_path = get_tool_config("corpus")
    env_path = config_dir / ".env"

    config = {
        "db_path": str(data_dir / "corpus.db"),
        "embed_batch_size": 32,
        "obsidian": {"vault_path": str(vault_path)},
        "whisper": {"model": whisper_size},
    }
    config_path.write_text(dump_yaml(config), encoding="utf-8")
    if not env_path.exists():
        env_path.write_text(
            "# shared secrets for fast-market tools\n", encoding="utf-8"
        )

    logger.info(
        "setup_complete",
        root_dir=str(root_dir),
        config_path=str(config_path),
        data_dir=str(data_dir),
        cache_dir=str(cache_dir),
        env_path=str(env_path),
    )
