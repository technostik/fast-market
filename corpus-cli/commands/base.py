from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandManifest:
    """
    Everything a command contributes to the system.

    Fields:
        name:          CLI name (e.g. "sync", "search").
        click_command: A fully-decorated @click.command (params may be extended
                       after creation by the registry injecting plugin options).
        api_router:    Optional FastAPI APIRouter with endpoints for this command.
        frontend_js:   Optional JS snippet injected into frontend pages.
    """

    name: str
    click_command: Any  # click.BaseCommand — avoid hard import at module level
    api_router: Any | None = None
    frontend_js: str | None = None
