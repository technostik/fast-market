from __future__ import annotations

from PIL import Image

from core.models import OverlayConfig, TextOverlayConfig
from core.overlay import apply_text_overlay, load_font, resolve_color


class TestResolveColor:
    def test_named(self):
        assert resolve_color("blue") == (0, 0, 255)

    def test_spaced_name(self):
        assert resolve_color("light green") == (144, 238, 144)

    def test_none(self):
        assert resolve_color("none") is None
        assert resolve_color(None) is None

    def test_hex(self):
        assert resolve_color("#ff8800") == (255, 136, 0)


class TestLoadFont:
    def test_fallback_when_missing(self):
        font = load_font("DefinitelyNotARealFont", 40)
        assert font is not None

    def test_dejavu_available(self):
        font = load_font("DejaVuSans", 40)
        assert font is not None

    def test_style_variant_fallback(self):
        # DejaVuSans has no bold variant file; should fall back gracefully
        font = load_font("DejaVuSans", 40, style="bold")
        assert font is not None


class TestOverlayConfig:
    def test_defaults(self):
        cfg = OverlayConfig()
        assert cfg.font == "Tomorrow"
        assert cfg.vpos == "bottom"
        assert cfg.style == "normal"

    def test_from_dict_partial(self):
        cfg = OverlayConfig.from_dict({"fg": "red", "effect": "box"})
        assert cfg.fg == "red"
        assert cfg.effect == "box"
        assert cfg.font == "Tomorrow"  # default preserved

    def test_to_dict_roundtrip(self):
        cfg = OverlayConfig.from_dict({"style": "italic"})
        assert cfg.to_dict()["style"] == "italic"


class TestApplyTextOverlay:
    def _img(self):
        return Image.new("RGB", (1024, 768), (30, 30, 30))

    def test_noop_when_disabled(self):
        cfg = TextOverlayConfig(enabled=False, text="x")
        out = apply_text_overlay(self._img(), cfg)
        assert out.size == (1024, 768)

    def test_noop_when_empty_text(self):
        cfg = TextOverlayConfig(enabled=True, text="")
        out = apply_text_overlay(self._img(), cfg)
        assert out.size == (1024, 768)

    def test_effects_preserve_size(self):
        for effect in ("none", "box", "shadow", "band"):
            cfg = TextOverlayConfig(
                enabled=True,
                text="Title\nsecond line",
                vpos="bottom",
                hpos="center",
                size="fit",
                fg="blue",
                bg="light green",
                effect=effect,
            )
            out = apply_text_overlay(self._img(), cfg, font_family="DejaVuSans")
            assert out.size == (1024, 768)
            assert out.mode == "RGB"

    def test_fixed_size_and_no_bg(self):
        cfg = TextOverlayConfig(
            enabled=True,
            text="TOPIC",
            vpos="top",
            hpos="left",
            size="64",
            fg="white",
            bg="none",
            effect="box",
        )
        out = apply_text_overlay(self._img(), cfg, font_family="DejaVuSans")
        assert out.size == (1024, 768)

    def test_png_alpha_roundtrip(self):
        img = Image.new("RGBA", (200, 200), (0, 0, 0, 255))
        cfg = TextOverlayConfig(enabled=True, text="Hi", effect="band", bg="red")
        out = apply_text_overlay(img, cfg, font_family="DejaVuSans")
        assert out.mode == "RGBA"

    def test_style_preserved(self):
        cfg = TextOverlayConfig(
            enabled=True, text="Bold", style="bold", effect="none"
        )
        out = apply_text_overlay(
            self._img(), cfg, font_family="DejaVuSans", font_style="bold"
        )
        assert out.size == (1024, 768)
