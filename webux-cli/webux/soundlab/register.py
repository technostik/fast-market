from __future__ import annotations

from pathlib import Path

from common.webux.base import WebuxPluginManifest
from webux.soundlab.plugin import _is_busy, router


def register(config: dict) -> WebuxPluginManifest:
    html = (Path(__file__).parent / "frontend.html").read_text(encoding="utf-8")
    return WebuxPluginManifest(
        name="soundlab",
        tab_label="Sound Lab",
        tab_icon="🧪",
        api_router=router,
        frontend_html=html,
        order=75,
        lazy=True,
        busy_check=_is_busy,
    )
