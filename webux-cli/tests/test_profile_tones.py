"""Profile colour tones: toolbar / publish component / pipeline rows.

Every profile gets a deterministic dark tone. The hub injects one
``[data-profile="<name>"]`` rule per profile plus a ``WEBUX_PROFILE_TONES``
map, so:
- the toolbar (``.webux-nav``) paints itself with the active profile's tone,
- long_publish / short_publish tint their publish component when the page
  picker changes,
- each short_publish pool row uses the tone of the profile it was queued with.

Run: pytest tests/test_profile_tones.py -v  (from webux-cli/)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from common.webux.base import WebuxPluginManifest  # noqa: E402
from common.webux.theme import (  # noqa: E402
    ALLOWED_VARS,
    DEFAULT_PROFILE_TONE,
    PROFILE_VARS,
    contrast_ratio,
    is_valid_profile_color,
    profile_tone,
    profile_tones,
    render_profile_css,
    tone_from_color,
)
from core.server import _WEBUX_PROFILE_SCRIPT, build_app  # noqa: E402

CLI_ROOT = Path(__file__).parent.parent
LONG_HTML = CLI_ROOT / "webux" / "long_publish" / "frontend.html"
SHORT_HTML = CLI_ROOT / "webux" / "short_publish" / "frontend.html"


def _make_client() -> TestClient:
    router = APIRouter()

    @router.get("/ping")
    def ping():
        return {"ok": True}

    plugin = WebuxPluginManifest(
        name="toneplug",
        tab_label="Tone",
        tab_icon="🎨",
        api_router=router,
        frontend_html="<html><head><title>t</title></head><body><main>hi</main></body></html>",
        lazy=True,
    )
    return TestClient(build_app(config={}, plugins={"toneplug": plugin}))


# ---------------------------------------------------------------------------
# Tone module
# ---------------------------------------------------------------------------


class TestProfileTone:
    def test_deterministic_across_calls(self):
        assert profile_tone("joriel") == profile_tone("joriel")
        assert profile_tone("joriel") != profile_tone("technostik")

    def test_tone_is_dark(self):
        for name in ("joriel", "technostik", "default"):
            tone = profile_tone(name)
            # Contrast against the near-white foreground stays very high.
            assert contrast_ratio(tone["bg"], tone["text"]) >= 4.5, name
            # The background is deliberately dark in every case.
            assert int(tone["bg"][1:3], 16) <= 0x40

    def test_tone_keys_are_canonical(self):
        expected = set(DEFAULT_PROFILE_TONE)
        assert set(profile_tone("anything")) == expected

    def test_empty_name_gets_neutral_default(self):
        assert profile_tone("") == DEFAULT_PROFILE_TONE
        assert profile_tone(None) == DEFAULT_PROFILE_TONE

    def test_even_hues_for_contrast(self):
        """Two profiles must not end up as two near-identical dark blues."""
        import colorsys

        tones = profile_tones(["joriel", "technostik"])

        def _hue(tone):
            h = tone["bg"].lstrip("#")
            r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
            return colorsys.rgb_to_hls(r, g, b)[0]

        delta = abs(_hue(tones["joriel"]) - _hue(tones["technostik"]))
        delta = min(delta, 1 - delta)
        assert delta > 0.25, f"hues too close: {delta}"

    def test_even_hues_scale_with_profile_count(self):
        for count in (2, 3, 4, 5):
            names = [f"p{i}" for i in range(count)]
            tones = profile_tones(names)
            assert len(tones) == count

    def test_color_override_wins(self):
        tones = profile_tones(["joriel", "technostik"], {"joriel": "#7c3aed"})
        assert tones["joriel"]["bg"] == "#7c3aed"
        # The other keeps the auto assignment.
        assert tones["technostik"]["bg"] != "#7c3aed"

    def test_invalid_override_falls_back_to_auto(self):
        tones = profile_tones(["joriel"], {"joriel": "not-a-color"})
        assert tones["joriel"]["bg"] != "not-a-color"

    def test_tone_from_color_derives_companions(self):
        tone = tone_from_color("#7c3aed")
        assert tone["bg"] == "#7c3aed"
        assert tone["border"] != tone["bg"]
        assert contrast_ratio(tone["bg"], tone["text"]) >= 4.5

    def test_color_validation(self):
        assert is_valid_profile_color("#7c3aed")
        assert is_valid_profile_color("#abc")
        assert not is_valid_profile_color("purple")
        assert not is_valid_profile_color("#12345")

    def test_render_css_has_a_rule_per_profile(self):
        css = render_profile_css(["joriel", "technostik"])
        assert '[data-profile="joriel"]' in css
        assert '[data-profile="technostik"]' in css
        for var in PROFILE_VARS:
            assert var in css

    def test_render_css_accepts_a_tone_map(self):
        tones = profile_tones(["joriel"], {"joriel": "#112233"})
        css = render_profile_css(tones)
        assert "--profile-bg: #112233;" in css

    def test_render_css_skips_unsafe_names(self):
        css = render_profile_css(['bad"name', "ok-name"])
        assert "bad" not in css
        assert '[data-profile="ok-name"]' in css

    def test_profile_vars_are_allowlisted(self):
        # Plugins reference --profile-* in their own CSS.
        assert PROFILE_VARS <= ALLOWED_VARS


# ---------------------------------------------------------------------------
# Server contract
# ---------------------------------------------------------------------------


class TestProfileServerContract:
    def _render(self, monkeypatch, profiles=("alpha", "beta"), active="alpha", overrides=None):
        import core.server as server

        monkeypatch.setattr(server, "_profile_names", lambda: list(profiles))
        monkeypatch.setattr(server, "resolve_profile", lambda: active)
        monkeypatch.setattr(
            server, "_profile_color_overrides", lambda: dict(overrides or {})
        )
        return _make_client().get("/toneplug").text

    def test_html_carries_active_profile(self, monkeypatch):
        html = self._render(monkeypatch)
        assert 'data-profile="alpha"' in html

    def test_profile_css_injected(self, monkeypatch):
        html = self._render(monkeypatch)
        assert '[data-profile="alpha"]' in html
        assert '[data-profile="beta"]' in html
        assert "--profile-bg:" in html

    def test_tone_map_exposed_to_scripts(self, monkeypatch):
        html = self._render(monkeypatch)
        assert "WEBUX_PROFILE_TONES" in html
        assert '"alpha"' in html and '"beta"' in html

    def test_nav_uses_profile_tone(self, monkeypatch):
        html = self._render(monkeypatch)
        assert "var(--profile-bg" in html
        assert "var(--profile-border" in html

    def test_nav_profile_select_shows_active_profile(self, monkeypatch):
        html = self._render(monkeypatch)
        assert 'id="webux-profile"' in html
        assert '<option value="alpha" selected>👤 alpha</option>' in html

    def test_profile_script_defines_public_helpers(self):
        for helper in (
            "window.webuxApplyProfile",
            "window.webuxProfileTone",
            "window.webuxApplyProfileTone",
            "webux-profile-change",
        ):
            assert helper in _WEBUX_PROFILE_SCRIPT, helper

    def test_config_override_reaches_the_page(self, monkeypatch):
        html = self._render(monkeypatch, overrides={"alpha": "#7c3aed"})
        assert "--profile-bg: #7c3aed;" in html
        assert '"alpha": {"bg": "#7c3aed"' in html


# ---------------------------------------------------------------------------
# Plugin pages
# ---------------------------------------------------------------------------


def test_long_publish_component_has_profile_surface():
    html = LONG_HTML.read_text(encoding="utf-8")
    assert 'class="wrap profile-surface"' in html
    assert ".wrap.profile-surface" in html
    assert "var(--profile-bg" in html
    assert "function applyProfileTone()" in html
    assert "webuxApplyProfileTone" in html


def test_short_publish_component_has_profile_surface():
    html = SHORT_HTML.read_text(encoding="utf-8")
    assert 'class="wrap profile-surface"' in html
    assert ".wrap.profile-surface" in html
    assert "webuxApplyProfileTone" in html


def test_short_publish_pipeline_rows_use_item_profile():
    html = SHORT_HTML.read_text(encoding="utf-8")
    assert "pool-row-profiled" in html
    # The row tone is set from the item's stored profile, falling back to the
    # page profile when older entries lack one.
    assert "item.profile || currentProfile()" in html
    assert re.search(r"webuxApplyProfileTone\(row,\s*rowProfile\)", html)
