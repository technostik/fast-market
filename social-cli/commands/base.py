from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CommandManifest:
    """Everything a command contributes to the system."""

    name: str
    click_command: Any
    api_router: Any | None = None
    frontend_js: str | None = None
