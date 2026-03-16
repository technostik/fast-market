from __future__ import annotations

from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger(__name__)


def _ask(prompt: str) -> str:
    value = input(prompt).strip()
    if not value:
        raise ValueError(f"Value is required for: {prompt}")
    return value


def run_wizard() -> None:
    channel_id = _ask("YouTube channel_id: ")
    client_secret = Path(_ask("YouTube client_secret.json path: "))
    vault_path = Path(_ask("Obsidian vault path: "))
    whisper_size = _ask("Whisper model size (tiny/base/small): ")

    if not client_secret.exists() or not client_secret.is_file():
        raise FileNotFoundError(f"Invalid client secret path: {client_secret}")
    if not vault_path.exists() or not vault_path.is_dir():
        raise FileNotFoundError(f"Invalid vault path: {vault_path}")

    config = {
        "db_path": "data/corpus.db",
        "embed_batch_size": 32,
        "obsidian": {"vault_path": str(vault_path)},
        "youtube": {"channel_id": channel_id, "client_secret_path": str(client_secret)},
        "whisper": {"model": whisper_size},
    }
    Path("config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    Path(".env").write_text("# add API keys here\n", encoding="utf-8")
    logger.info("setup_complete", config_path="config.yaml", env_path=".env")
