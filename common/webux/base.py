from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WebuxPluginManifest:
    """Everything a package contributes to the webux hub."""

    name: str
    tab_label: str
    tab_icon: str
    frontend_html: str
    api_router: Any | None = None
    order: int = 100
    lazy: bool = True
    #: Toolbar group for the grouped-dropdown nav (e.g. "Publish").
    #: Empty = grouped by the hub's built-in mapping, else "More".
    group: str = ""
