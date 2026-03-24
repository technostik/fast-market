from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CommandManifest:
    """
    Everything a command contributes to the system.

    Fields:
        name:          CLI name (e.g. "search", "comments").
        click_command: A fully-decorated @click.command.
        api_router:    Optional FastAPI APIRouter.
        frontend_js:   Optional JS snippet.
    """

    name: str
    click_command: Any
    api_router: Any | None = None
    frontend_js: str | None = None
