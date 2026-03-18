from __future__ import annotations

from pathlib import Path

from common import structlog
import yaml

from common.core.paths import get_fastmarket_dir, get_tool_cache_dir, get_tool_config, get_tool_data_dir

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
        "youtube": {"channel_id": channel_id, "client_secret_path": str(client_secret)},
        "whisper": {"model": whisper_size},
    }
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    if not env_path.exists():
        env_path.write_text("# shared secrets for fast-market tools\n", encoding="utf-8")

    logger.info(
        "setup_complete",
        root_dir=str(root_dir),
        config_path=str(config_path),
        data_dir=str(data_dir),
        cache_dir=str(cache_dir),
        env_path=str(env_path),
    )
