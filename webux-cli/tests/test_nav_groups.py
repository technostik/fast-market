from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from common.webux.base import WebuxPluginManifest
from core.server import (
    _WEBUX_GROUP_FALLBACK,
    _build_nav,
    _plugin_group,
    build_app,
)


def _manifest(name: str, **kwargs) -> WebuxPluginManifest:
    return WebuxPluginManifest(
        name=name,
        tab_label=name,
        tab_icon="x",
        frontend_html="<html><body></body></html>",
        **kwargs,
    )


class TestGrouping:
    def test_manifest_group_wins_over_fallback(self):
        assert _plugin_group(_manifest("long_publish")) == "Publish"
        assert _plugin_group(_manifest("long_publish", group="Custom")) == "Custom"
        assert _plugin_group(_manifest("something_new")) == "More"

    def test_fallback_covers_known_tabs(self):
        for name in (
            "fileviewer", "skill_runner", "short_publish", "long_publish",
            "yt_poster", "yt_thumbnail", "storyboard", "voiceboard",
            "charisma", "monitor",
        ):
            assert name in _WEBUX_GROUP_FALLBACK, name

    def test_build_nav_emits_dropdowns_with_deep_links(self):
        plugins = {
            "long_publish": _manifest("long_publish"),
            "yt_thumbnail": _manifest("yt_thumbnail", group="Publish"),
            "monitor": _manifest("monitor"),
        }
        nav = _build_nav(plugins, active="yt_thumbnail")
        assert nav.count("webux-dropdown") >= 2
        assert 'href="/long_publish"' in nav
        assert 'href="/yt_thumbnail"' in nav
        assert 'href="/monitor"' in nav
        # Active tab marks its item and its group button.
        assert '<a class="active" href="/yt_thumbnail">' in nav
        assert "webux-dropbtn active" in nav

    def test_no_flat_tab_links_outside_menus(self):
        """Every tab link must live inside a dropdown menu (short bar)."""
        plugins = {n: _manifest(n) for n in ("a", "b", "c")}
        nav = _build_nav(plugins)
        assert nav.count('class="webux-dropdown"') == 1  # all in More
        assert nav.count('href="/a"') == 1


class TestNavScript:
    def test_page_contains_dropdown_behavior(self):
        app = build_app(config={}, plugins={"only": _manifest("only")})
        html = TestClient(app).get("/only").text
        assert "webux-dropbtn" in html
        assert "webux-dropdown" in html
        assert "webux-menu" in html
        # Toggle + outside-click + Escape handlers injected.
        assert ".webux-dropdown.open" in html
        assert "Escape" in html

    def test_shell_page_contains_groups(self):
        app = build_app(
            config={},
            plugins={"long_publish": _manifest("long_publish"), "monitor": _manifest("monitor")},
        )
        html = TestClient(app).get("/shell").text
        assert "Publish" in html and "Observe" in html
        assert "/long_publish" in html and "/monitor" in html
