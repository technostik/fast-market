"""L0 (static) + L1 (contract) regression tests for the unified webux theme.

Covers:
- theme module: 3 themes, dark preserves legacy palette, body contrast >= 4.5
- server contract: /theme.css, /api/system/theme GET+POST, selector injection,
  ?theme= override, config default, shell page
- static lint: no `:root {` in plugin sources, var() allowlist, no leftover
  dark hardcoded hexes in plugin sources

Run: pytest tests/test_theme.py -v  (from webux-cli/)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from common.webux.base import WebuxPluginManifest  # noqa: E402
from common.webux.theme import (  # noqa: E402
    ALLOWED_VARS,
    DEFAULT_THEME,
    THEME_NAMES,
    THEMES,
    contrast_ratio,
    render_all_themes_css,
    resolve_theme,
)
from core.server import _inject_nav, build_app  # noqa: E402

CLI_ROOT = Path(__file__).parent.parent

# Hardcoded dark-palette hexes that must NOT appear in plugin sources anymore.
# (They would not adapt to light/blue. #fff/#000/#666 intentional accents excluded.)
BANNED_HEXES = [
    "#1a1a2e",
    "#16213e",
    "#0f172a",
    "#1d2a4a",
    "#26395f",
    "#0f3460",
    "#3a1a1a",
    "#9ecbff",
]

PLUGIN_SOURCES = [
    CLI_ROOT / "webux" / "fileviewer" / "register.py",
    CLI_ROOT / "webux" / "skill_runner" / "register.py",
    CLI_ROOT / "webux" / "yt_poster" / "register.py",
    CLI_ROOT / "webux" / "storyboard" / "register.py",
    CLI_ROOT / "webux" / "voiceboard" / "register.py",
    CLI_ROOT / "webux" / "short_publish" / "frontend.html",
    CLI_ROOT / "webux" / "long_publish" / "frontend.html",
    CLI_ROOT / "webux" / "charisma" / "frontend.html",
]

REPO_ROOT = CLI_ROOT.parent

# Tabs from other CLIs that contribute pages to `webux serve`.
EXTERNAL_SOURCES = [
    REPO_ROOT / "corpus-cli" / "webux" / "corpus" / "register.py",
    REPO_ROOT / "corpus-cli" / "webux" / "corpus_browser" / "frontend.html",
    REPO_ROOT / "monitor-cli" / "webux" / "monitor" / "register.py",
    REPO_ROOT / "watcher-cli" / "webux" / "watcher" / "register.py",
]

ALL_SOURCES = PLUGIN_SOURCES + EXTERNAL_SOURCES

# Pages that used `body{padding:16px}` and now carry their padding on
# `main.webux-page` so the tab bar stays full-bleed on every tab.
PADDED_PAGES = [
    CLI_ROOT / "webux" / "yt_poster" / "register.py",
    CLI_ROOT / "webux" / "short_publish" / "frontend.html",
    CLI_ROOT / "webux" / "long_publish" / "frontend.html",
    REPO_ROOT / "corpus-cli" / "webux" / "corpus" / "register.py",
    REPO_ROOT / "corpus-cli" / "webux" / "corpus_browser" / "frontend.html",
    REPO_ROOT / "monitor-cli" / "webux" / "monitor" / "register.py",
    REPO_ROOT / "watcher-cli" / "webux" / "watcher" / "register.py",
]


def _make_client(config: dict | None = None) -> TestClient:
    router = APIRouter()

    @router.get("/ping")
    def ping():
        return {"ok": True}

    plugin = WebuxPluginManifest(
        name="themeplug",
        tab_label="Theme",
        tab_icon="🎨",
        api_router=router,
        frontend_html="<html><head><title>t</title></head><body><main>hi</main></body></html>",
        lazy=True,
    )
    app = build_app(config=config or {}, plugins={"themeplug": plugin})
    return TestClient(app)


# ---------------------------------------------------------------------------
# Theme module
# ---------------------------------------------------------------------------


class TestThemeModule:
    def test_three_themes_present(self):
        assert set(THEME_NAMES) == {"dark", "light", "blue"}
        assert DEFAULT_THEME == "dark"
        for name in THEME_NAMES:
            assert name in THEMES

    def test_dark_preserves_legacy_palette(self):
        """Dark must equal the pre-unification hardcoded values (no visual change)."""
        dark = THEMES["dark"]
        assert dark["--bg"] == "#1a1a2e"
        assert dark["--bg-secondary"] == "#16213e"
        assert dark["--text"] == "#eee"
        assert dark["--text-dim"] == "#888"
        assert dark["--accent"] == "#0f3460"
        assert dark["--success"] == "#4ade80"
        assert dark["--error"] == "#f87171"
        assert dark["--warning"] == "#fbbf24"
        assert dark["--border"] == "#333"
        assert dark["--link"] == "#7dd3fc"

    def test_all_themes_have_canonical_vars(self):
        canonical = set(THEMES["dark"].keys())
        for name in THEME_NAMES:
            assert set(THEMES[name].keys()) == canonical, name

    def test_body_contrast_readable_in_every_theme(self):
        for name in THEME_NAMES:
            ratio = contrast_ratio(THEMES[name]["--bg"], THEMES[name]["--text"])
            assert ratio >= 4.5, f"{name}: body contrast {ratio:.2f} < 4.5"

    def test_resolve_theme(self):
        assert resolve_theme({}) == "dark"
        assert resolve_theme({"theme": "light"}) == "light"
        assert resolve_theme({"theme": "blue"}) == "blue"
        assert resolve_theme({"theme": "bogus"}) == "dark"
        assert resolve_theme({}, override="light") == "light"
        assert resolve_theme({"theme": "light"}, override="blue") == "blue"
        assert resolve_theme({}, override="bogus") == "dark"

    def test_rendered_css_covers_all_themes(self):
        css = render_all_themes_css()
        assert ":root" in css  # dark default
        for name in THEME_NAMES:
            assert f'[data-theme="{name}"]' in css, name
            for var, value in THEMES[name].items():
                assert f"{var}: {value};" in css


# ---------------------------------------------------------------------------
# Server contract
# ---------------------------------------------------------------------------


class TestThemeServerContract:
    def test_theme_css_served(self):
        client = _make_client()
        resp = client.get("/theme.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]
        for name in THEME_NAMES:
            assert f'[data-theme="{name}"]' in resp.text

    def test_system_theme_get_and_post(self):
        client = _make_client()
        resp = client.get("/api/system/theme")
        assert resp.status_code == 200
        body = resp.json()
        assert body["theme"] == "dark"
        assert body["available"] == ["dark", "light", "blue"]
        assert body["codemirror"]["dark"] == "dracula"
        assert body["codemirror"]["light"] == "default"
        assert body["codemirror"]["blue"] == "dracula"

        resp = client.post("/api/system/theme", json={"theme": "light"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "theme": "light"}
        assert client.get("/api/system/theme").json()["theme"] == "light"

    def test_system_theme_post_rejects_unknown(self):
        client = _make_client()
        resp = client.post("/api/system/theme", json={"theme": "neon"})
        assert resp.status_code == 400

    def test_config_theme_is_server_default(self):
        client = _make_client(config={"theme": "blue"})
        assert client.get("/api/system/theme").json()["theme"] == "blue"
        page = client.get("/themeplug")
        assert 'data-theme="blue"' in page.text
        assert '<option value="blue" selected>' in page.text

    def test_page_injects_selector_and_all_themes(self):
        client = _make_client()
        page = client.get("/themeplug")
        assert page.status_code == 200
        assert 'id="webux-theme"' in page.text
        assert "webuxSetTheme" in page.text
        assert "webux-theme" in page.text  # localStorage key
        assert 'data-theme="dark"' in page.text
        for name in THEME_NAMES:
            assert f'<option value="{name}"' in page.text
            assert f'[data-theme="{name}"]' in page.text

    def test_page_theme_query_override(self):
        client = _make_client()
        page = client.get("/themeplug?theme=light")
        assert 'data-theme="light"' in page.text
        assert '<option value="light" selected>' in page.text

    def test_page_theme_query_invalid_falls_back(self):
        client = _make_client()
        page = client.get("/themeplug?theme=bogus")
        assert 'data-theme="dark"' in page.text

    def test_shell_page_has_selector(self):
        client = _make_client()
        page = client.get("/shell")
        assert page.status_code == 200
        assert 'id="webux-theme"' in page.text
        assert 'data-theme="dark"' in page.text

    def test_inject_nav_without_head(self):
        html = _inject_nav("<p>bare</p>", "<nav>x</nav>")
        assert 'id="webux-theme"' not in html  # nav passed has no selector; css still injected
        assert "[data-theme=" in html

    def test_nav_chrome_is_isolated_from_plugin_css(self):
        """Hostile plugin CSS (generic button/select/body rules) must not move the nav.

        The hub stylesheet is injected AFTER the plugin's own <style> so hub
        rules win ties, and nav controls use `font: inherit` + `width: auto`
        to neutralize generic `button`/`select` leaks.
        """
        from core.server import _NAV_LAYOUT

        hostile = WebuxPluginManifest(
            name="hostile",
            tab_label="Hostile",
            tab_icon="x",
            api_router=None,
            frontend_html=(
                "<html><head><style>"
                "* { box-sizing: content-box; }"
                "body { font-size: 9px; font-family: 'Comic Sans MS'; }"
                "button { font-weight: 900; font-size: 99px; border: none; padding: 0; }"
                "select { width: 100%; font-size: 99px; }"
                "a { text-decoration: underline; }"
                "</style></head><body><p>hi</p></body></html>"
            ),
        )
        app = build_app(config={}, plugins={"hostile": hostile})
        html = TestClient(app).get("/hostile").text
        plugin_pos = html.find("Comic Sans")
        hub_pos = html.find(".webux-nav .theme-select")
        assert plugin_pos != -1 and hub_pos != -1
        assert hub_pos > plugin_pos, "hub CSS must come after plugin CSS in <head>"
        # Guard rules present in the served page.
        for guard in (
            ".webux-nav .theme-select",
            ".webux-nav .exit-btn",
            "font: inherit",
            "width: auto",
            "box-sizing: border-box",
        ):
            assert guard in html, guard
        # Unified base font shipped for body + nav.
        assert "font-size: 14px" in html
        assert _NAV_LAYOUT.strip() in html


# ---------------------------------------------------------------------------
# L0 static lint: plugins must not own :root / must use allowed vars
# ---------------------------------------------------------------------------


class TestThemeStaticLint:
    def test_no_plugin_declares_own_root(self):
        offenders = []
        for src in ALL_SOURCES:
            if not src.exists():
                continue
            text = src.read_text(encoding="utf-8")
            if re.search(r"^\s*:root\s*\{", text, re.MULTILINE):
                offenders.append(str(src))
        assert not offenders, f"plugins must not declare :root (hub injects it): {offenders}"

    def test_plugin_vars_are_allowlisted(self):
        unknown: dict[str, set[str]] = {}
        for src in ALL_SOURCES:
            if not src.exists():
                continue
            text = src.read_text(encoding="utf-8")
            used = set(re.findall(r"var\(\s*(--[a-zA-Z0-9_-]+)", text))
            bad = {v for v in used if v not in ALLOWED_VARS}
            if bad:
                unknown[str(src)] = bad
        assert not unknown, f"unknown CSS vars (add to common/webux/theme.py): {unknown}"

    def test_no_banned_dark_hex_in_plugins(self):
        offenders: dict[str, list[str]] = {}
        for src in ALL_SOURCES:
            if not src.exists():
                continue
            lowered = src.read_text(encoding="utf-8").lower()
            found = [h for h in BANNED_HEXES if h in lowered]
            if found:
                offenders[str(src)] = found
        assert not offenders, f"hardcoded dark hexes would break light/blue: {offenders}"

    def test_no_plugin_body_padding(self):
        """No tab may set body padding: it insets the tab bar.

        Page padding belongs on `main.webux-page` (hub keeps `body{padding:0}`
        so the tab bar is full-bleed and identical on every tab).
        """
        offenders = []
        for src in ALL_SOURCES:
            if not src.exists():
                continue
            text = src.read_text(encoding="utf-8")
            for match in re.finditer(r"(?<![\w.\#-])body\s*\{([^}]*)\}", text):
                if re.search(r"padding\s*:\s*(?!0[;\s}])", match.group(1)):
                    offenders.append(str(src))
                    break
        assert not offenders, f"body padding insets the tab bar, use main.webux-page: {offenders}"

    def test_hub_body_has_no_padding(self):
        from core.server import _NAV_LAYOUT

        match = re.search(r"^body\s*\{([^}]*)\}", _NAV_LAYOUT, re.MULTILINE)
        assert match, "hub must style body"
        assert re.search(r"padding\s*:\s*0\s*;", match.group(1)), "hub body must pin padding: 0"
        assert ".webux-page" in _NAV_LAYOUT

    def test_padded_pages_use_webux_page_wrapper(self):
        missing = []
        for src in PADDED_PAGES:
            if not src.exists():
                missing.append(f"{src} (absent)")
                continue
            text = src.read_text(encoding="utf-8")
            if '<main class="webux-page">' not in text or "</main>" not in text:
                missing.append(str(src))
        assert not missing, f"pages needing content padding must wrap in main.webux-page: {missing}"

    def test_codemirror_editors_follow_theme(self):
        """fileviewer + skill_runner must init from data-theme and listen for changes."""
        for name in ("fileviewer", "skill_runner"):
            text = (CLI_ROOT / "webux" / name / "register.py").read_text(encoding="utf-8")
            assert "webux-theme-change" in text, name
            assert "data-cm-theme" in text and "dracula" in text, name
