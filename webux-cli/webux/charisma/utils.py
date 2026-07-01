from __future__ import annotations

import shutil

from common.core.config import load_tool_config, save_tool_config

from .models import DEFAULT_EXTENSIONS, DEFAULT_FOLDER


def _sound() -> str:
    return shutil.which("sound") or "sound"


def load_charisma_cfg() -> dict:
    try:
        cfg = load_tool_config("charisma")
        return cfg.get("charisma", {})
    except Exception:
        return {}


def save_charisma_cfg(folder: str, extensions: str) -> None:
    try:
        cfg = load_tool_config("charisma")
        cfg["charisma"] = {"folder": folder, "extensions": extensions}
        save_tool_config("charisma", cfg)
    except Exception:
        pass


def default_folder() -> str:
    return load_charisma_cfg().get("folder", DEFAULT_FOLDER)


def default_extensions() -> str:
    return load_charisma_cfg().get("extensions", DEFAULT_EXTENSIONS)
