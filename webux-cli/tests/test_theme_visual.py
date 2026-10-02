"""L2 browser regression tests for the unified webux theme (dark/light/blue).

Requires: playwright + chromium (already in this env).
Run:  pytest tests/test_theme_visual.py -v
      pytest tests/test_theme_visual.py -v --update-snapshots   # refresh goldens

What is covered:
- theme selector exists on every tab and switches data-theme without reload
- per-browser persistence via localStorage across reload
- body background/text resolve to the theme palette in every theme
- body text contrast >= 4.5 in every theme x tab (catches unreadable themes)
- screenshots saved to tests/__snapshots__/ for manual review + pixel diff
  against goldens when present (tolerance 2%).

Skipped automatically when playwright browsers are unavailable.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

playwright = pytest.importorskip("playwright.sync_api")

from common.webux.theme import THEMES, contrast_ratio  # noqa: E402

SNAPSHOT_DIR = Path(__file__).parent / "__snapshots__"

TABS = [
    "fileviewer",
    "skill_runner",
    "yt_poster",
    "short_publish",
    "long_publish",
    "storyboard",
    "voiceboard",
    "charisma",
]

# Tabs contributed by other CLIs. Served with api_router=None (HTML-only):
# geometry/palette/selector assertions don't need backends, and this avoids
# cross-CLI `core.*` collisions in the test process.
EXTERNAL_TABS = [
    ("/corpus-cli", "webux.corpus.register"),
    ("/corpus-cli", "webux.corpus_browser.register"),
    ("/monitor-cli", "webux.monitor.register"),
    ("/watcher-cli", "webux.watcher.register"),
]

ALL_TABS = TABS + ["corpus", "corpus_browser", "monitor", "watcher"]

THEME_LIST = ["dark", "light", "blue"]


def _load_external_html(cli_suffix: str, module: str):
    """Import an external webux register.py and return its manifest (HTML-only use).

    Other CLIs ship colliding top-level packages (`core`, `webux`), so the
    import happens with those modules temporarily evicted (same approach as
    `common.webux.registry._discover_from_repo_layout`). Only `frontend_html`
    and display metadata are kept; the router is dropped (api_router=None).
    """
    import importlib

    repo_root = Path(__file__).parent.parent.parent
    cli_dir = str(repo_root / cli_suffix.lstrip("/"))
    saved = {
        name: mod
        for name, mod in sys.modules.items()
        if name in ("core", "webux") or name.startswith(("core.", "webux."))
    }
    for name in saved:
        sys.modules.pop(name, None)
    sys.path.insert(0, cli_dir)
    try:
        mod = importlib.import_module(module)
        manifest = mod.register({})
        from common.webux.base import WebuxPluginManifest

        return WebuxPluginManifest(
            name=manifest.name,
            tab_label=manifest.tab_label,
            tab_icon=manifest.tab_icon,
            frontend_html=manifest.frontend_html,
            api_router=None,
            order=manifest.order,
            lazy=False,
        )
    finally:
        sys.path.remove(cli_dir)
        for name in list(sys.modules):
            if name in ("core", "webux") or name.startswith(("core.", "webux.")):
                sys.modules.pop(name, None)
        sys.modules.update(saved)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _rgb_to_hex(css: str) -> str:
    """'rgb(255, 255, 255)' -> '#ffffff' (also passes through #hex)."""
    css = css.strip()
    if css.startswith("#"):
        h = css.lower()
        if len(h) == 4:
            h = "#" + "".join(c * 2 for c in h[1:])
        return h
    import re

    m = re.match(r"rgba?\(([^)]+)\)", css)
    if not m:
        raise ValueError(f"cannot parse color: {css}")
    parts = [p.strip() for p in m.group(1).split(",")][:3]
    return "#{:02x}{:02x}{:02x}".format(*[int(float(p)) for p in parts])


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Start the real webux app (all 8 tabs) on a free port.

    Isolated HOME/XDG: plugin pages render workdir-backed data (short_publish
    pool, voiceboard/storyboard state, file trees). Pointing HOME at an empty
    temp dir keeps screenshots deterministic regardless of the developer's
    real workdir contents.
    """
    from webux.charisma.register import register as reg_charisma
    from webux.fileviewer.register import register as reg_fileviewer
    from webux.long_publish.register import register as reg_long
    from webux.short_publish.register import register as reg_short
    from webux.skill_runner.register import register as reg_skill
    from webux.storyboard.register import register as reg_story
    from webux.voiceboard.register import register as reg_voice
    from webux.yt_poster.register import register as reg_yt

    import uvicorn

    from core.server import build_app

    regs = [
        reg_fileviewer,
        reg_skill,
        reg_yt,
        reg_short,
        reg_long,
        reg_story,
        reg_voice,
        reg_charisma,
    ]
    import os
    import tempfile

    def _reset_plugin_state() -> None:
        """Clear in-memory stores other test modules may have populated.

        pytest runs in one process: short_publish pool tests leave jobs in
        module globals, which the live server would otherwise render.
        """
        try:
            from webux.short_publish import pool as short_pool

            short_pool._pool = []
            short_pool._pool_state = {"running": False, "current": None}
        except Exception:
            pass
        for modname in (
            "webux.short_publish.register",
            "webux.long_publish.register",
            "webux.charisma.register",
        ):
            try:
                mod = sys.modules.get(modname) or __import__(modname, fromlist=["_jobs"])
                jobs = getattr(mod, "_jobs", None)
                if isinstance(jobs, dict):
                    jobs.clear()
            except Exception:
                pass

    fake_home = tempfile.mkdtemp(prefix="webux-theme-test-home-")
    real_home = os.path.expanduser("~")  # resolved BEFORE HOME is overridden
    saved_env = {
        key: os.environ.get(key)
        for key in (
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
            "FASTMARKET_CONFIG_DIR",
            "PLAYWRIGHT_BROWSERS_PATH",
        )
    }
    os.environ["HOME"] = fake_home
    os.environ["XDG_CONFIG_HOME"] = os.path.join(fake_home, ".config")
    os.environ["XDG_DATA_HOME"] = os.path.join(fake_home, ".local", "share")
    os.environ["XDG_CACHE_HOME"] = os.path.join(fake_home, ".cache")
    os.environ.pop("FASTMARKET_CONFIG_DIR", None)
    # Playwright browsers live in the real ~/.cache — keep them reachable.
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(real_home, ".cache", "ms-playwright")
    try:
        plugins = {}
        for fn in regs:
            try:
                m = fn({})
                plugins[m.name] = m
            except Exception as exc:  # pragma: no cover - surface clearly
                raise RuntimeError(f"plugin register() failed: {exc}") from exc
        for cli_suffix, module in EXTERNAL_TABS:
            try:
                m = _load_external_html(cli_suffix, module)
                plugins[m.name] = m
            except Exception as exc:  # pragma: no cover - surface clearly
                raise RuntimeError(f"external plugin {module} failed: {exc}") from exc

        app = build_app(config={}, plugins=plugins)
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"
        # Wait for readiness.
        import urllib.request

        for _ in range(100):
            try:
                with urllib.request.urlopen(f"{base}/shell", timeout=2):
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("test server did not start")
        _reset_plugin_state()
        yield base
        server.should_exit = True
        thread.join(timeout=10)
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="module")
def browser_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"chromium unavailable: {exc}")
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        yield page
        browser.close()


def _set_theme(page, theme: str) -> None:
    page.evaluate(
        f"""() => {{
            localStorage.setItem('webux-theme', '{theme}');
            document.documentElement.setAttribute('data-theme', '{theme}');
            const sel = document.getElementById('webux-theme');
            if (sel) sel.value = '{theme}';
        }}"""
    )
    page.wait_for_timeout(150)


def test_nav_chrome_identical_on_every_tab(live_server, browser_page):
    """The tab bar must render identically on every tab.

    Regression test: plugin CSS used to leak into the nav (body font-size,
    generic `button`/`select` rules), so tab size/font varied per component.
    """
    per_theme: dict[str, dict[str, tuple]] = {}
    for theme in THEME_LIST:
        seen: dict[str, tuple] = {}
        for tab in ALL_TABS:
            browser_page.goto(f"{live_server}/{tab}", wait_until="domcontentloaded")
            _set_theme(browser_page, theme)
            snapshot = browser_page.evaluate(
                """() => {
                    const nav = document.querySelector('nav.webux-nav');
                    const link = nav.querySelector('a');
                    const sel = document.getElementById('webux-theme');
                    const exit = nav.querySelector('.exit-btn');
                    const cs = (el, p) => getComputedStyle(el)[p];
                    const r = nav.getBoundingClientRect();
                    return {
                        navRect: [r.left, r.width, r.height],
                        linkFont: [cs(link,'fontFamily'), cs(link,'fontSize'), cs(link,'fontWeight')],
                        selFont: [cs(sel,'fontFamily'), cs(sel,'fontSize'), cs(sel,'fontWeight')],
                        selW: sel.getBoundingClientRect().width,
                        exitFont: [cs(exit,'fontFamily'), cs(exit,'fontSize'), cs(exit,'fontWeight')],
                        exitH: exit.getBoundingClientRect().height,
                    };
                }"""
            )
            # The theme dropdown must never go full-width (plugin `select{width:100%}` leak).
            assert snapshot["selW"] < 400, f"{tab}/{theme}: theme select width {snapshot['selW']}"
            # The tab bar must be full-bleed: body padding would inset it
            # (this split tabs into two visually distinct sets).
            assert snapshot["navRect"][0] == 0, f"{tab}/{theme}: nav left inset"
            assert snapshot["navRect"][1] == 1280, f"{tab}/{theme}: nav width {snapshot['navRect'][1]}"
            key = (
                tuple(snapshot["navRect"]),
                tuple(snapshot["linkFont"]),
                tuple(snapshot["selFont"]),
                tuple(snapshot["exitFont"]),
                snapshot["exitH"],
            )
            seen[tab] = key
        per_theme[theme] = seen
        first_tab, first_key = next(iter(seen.items()))
        for tab, key in seen.items():
            assert key == first_key, (
                f"nav chrome differs on '{tab}' vs '{first_tab}' in theme '{theme}':\n"
                f"  {tab}: {key}\n  {first_tab}: {first_key}"
            )


def test_selector_present_on_every_tab(live_server, browser_page):
    for tab in ALL_TABS:
        browser_page.goto(f"{live_server}/{tab}", wait_until="domcontentloaded")
        assert browser_page.locator("#webux-theme").count() == 1, tab
        assert browser_page.locator("nav.webux-nav").count() == 1, tab
        assert browser_page.evaluate("document.documentElement.getAttribute('data-theme')") in THEME_LIST


def test_selector_switch_persists_per_browser(live_server, browser_page):
    browser_page.goto(f"{live_server}/fileviewer", wait_until="domcontentloaded")
    browser_page.select_option("#webux-theme", "light")
    browser_page.wait_for_timeout(200)
    assert browser_page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"
    assert browser_page.evaluate("localStorage.getItem('webux-theme')") == "light"
    browser_page.goto(f"{live_server}/skill_runner", wait_until="domcontentloaded")
    # Boot script restores persisted theme before paint.
    assert browser_page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"
    # Restore dark for other tests.
    browser_page.select_option("#webux-theme", "dark")
    browser_page.wait_for_timeout(200)


def test_theme_palette_applies_per_tab(live_server, browser_page):
    """Computed body colors must equal the theme palette in every tab x theme."""
    for theme in THEME_LIST:
        expected_bg = THEMES[theme]["--bg"]
        for tab in ALL_TABS:
            browser_page.goto(f"{live_server}/{tab}", wait_until="domcontentloaded")
            _set_theme(browser_page, theme)
            bg = _rgb_to_hex(
                browser_page.evaluate(
                    "getComputedStyle(document.body).backgroundColor"
                )
            )
            fg = _rgb_to_hex(
                browser_page.evaluate("getComputedStyle(document.body).color")
            )
            assert bg == expected_bg, f"{tab}/{theme}: body bg {bg} != {expected_bg}"
            ratio = contrast_ratio(bg, fg)
            assert ratio >= 4.5, f"{tab}/{theme}: body contrast {ratio:.2f} < 4.5"


def test_screenshots_against_goldens(live_server, browser_page, request):
    """Pixel-diff each tab x theme against tests/__snapshots__/ goldens.

    Missing goldens are created (and the test passes with a notice).
    Pass --update-snapshots to refresh all goldens after intentional changes.
    """
    update = bool(request.config.getoption("update_snapshots", default=False))
    try:
        from PIL import Image, ImageChops
    except ImportError:
        pytest.skip("PIL unavailable for pixel diff")

    SNAPSHOT_DIR.mkdir(exist_ok=True)
    failures: list[str] = []

    def _settle() -> None:
        """Wait for the tab's init fetches (config/state/workdir) to finish rendering."""
        try:
            browser_page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        try:
            browser_page.evaluate("document.fonts ? document.fonts.ready.then(() => 0) : 0")
        except Exception:
            pass
        browser_page.wait_for_timeout(500)

    def _capture(tab: str, theme: str) -> bytes:
        try:
            browser_page.goto(f"{live_server}/{tab}", wait_until="domcontentloaded", timeout=15000)
        except Exception:
            browser_page.goto(f"{live_server}/{tab}", wait_until="domcontentloaded")
        _set_theme(browser_page, theme)
        _settle()
        return browser_page.screenshot()

    def _diff_pct(shot: bytes, golden_path: Path) -> float | str:
        import io

        a = Image.open(io.BytesIO(shot)).convert("RGB")
        b = Image.open(golden_path).convert("RGB")
        if a.size != b.size:
            return f"size {a.size} != golden {b.size}"
        diff = ImageChops.difference(a, b)
        hist = diff.histogram()
        differing = sum(count for i, count in enumerate(hist) if (i % 256) > 12)
        total = a.size[0] * a.size[1] * 3
        return differing / total

    for theme in THEME_LIST:
        for tab in ALL_TABS:
            shot = _capture(tab, theme)
            golden = SNAPSHOT_DIR / f"{tab}-{theme}.png"
            if update or not golden.exists():
                golden.write_bytes(shot)
                continue
            result = _diff_pct(shot, golden)
            if isinstance(result, str):
                failures.append(f"{tab}/{theme}: {result}")
                continue
            if result > 0.02:
                # Retry settled captures: tab init fetches can resolve mid-frame
                # (notably voiceboard/storyboard config+state selects).
                for _ in range(3):
                    _settle()
                    result = _diff_pct(browser_page.screenshot(), golden)
                    if not isinstance(result, str) and result <= 0.02:
                        break
                if isinstance(result, str) or result > 0.02:
                    failures.append(f"{tab}/{theme}: {result if isinstance(result, str) else f'{result:.2%} pixels differ (>2%)'}")
    assert not failures, "visual regressions:\n" + "\n".join(failures)
