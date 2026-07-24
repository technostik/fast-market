from __future__ import annotations

from pathlib import Path

from common import structlog
from common.core.paths import get_tool_data_dir

logger = structlog.get_logger(__name__)

_POINTER_FILENAME = "active_collection"


def _pointer_path(profile: str | None = None) -> Path:
    return get_tool_data_dir("rag", profile) / _POINTER_FILENAME


def read_active_collection(profile: str | None = None) -> str | None:
    p = _pointer_path(profile)
    if not p.exists():
        return None
    name = p.read_text(encoding="utf-8").strip()
    return name or None


def write_active_collection(name: str, profile: str | None = None) -> None:
    if not name or not name.strip():
        raise ValueError("Collection name cannot be empty")
    p = _pointer_path(profile)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(name.strip() + "\n", encoding="utf-8")
    logger.info("active_collection_set", name=name.strip())


def resolve_collection_name(
    cli_override: str | None = None, profile: str | None = None
) -> str:
    if cli_override:
        return cli_override.strip()
    active = read_active_collection(profile)
    if active:
        return active
    raise SystemExit(
        "No active collection. Run:\n"
        "  rag collection create <name>\n"
        "  rag collection use <name>"
    )
