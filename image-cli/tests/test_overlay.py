from __future__ import annotations

from pathlib import Path

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

    def test_hex_shorthand(self):
        assert resolve_color("#f80") == (255, 136, 0)

    def test_hex_0x(self):
        assert resolve_color("0xff8800") == (255, 136, 0)

    def test_hex_bare(self):
        assert resolve_color("ff8800") == (255, 136, 0)
        assert resolve_color("f80") == (255, 136, 0)

    def test_hex_with_alpha_ignored(self):
        # alpha channel is dropped, rgb returned
        assert resolve_color("#ff8800aa") == (255, 136, 0)


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

    def test_band_size_pct(self):
        # band should be full width and ~band_size% of image height
        cfg = TextOverlayConfig(
            enabled=True, text="Title", vpos="top", hpos="center",
            effect="band", bg="red", band_size=10,
        )
        img = Image.new("RGB", (1000, 500), (0, 0, 0))
        out = apply_text_overlay(img, cfg, font_family="DejaVuSans")
        assert out.size == (1000, 500)
        # band height for 10% of 500px should be ~50px; just ensure it ran
        assert out.mode == "RGB"


class TestSaveOutput:
    def test_default_suffix(self, tmp_path):
        from commands.overlay.register import _save_output
        from PIL import Image

        img = Image.new("RGB", (64, 48), (10, 20, 30))
        out_path = tmp_path / "out.png"
        saved = _save_output(img, str(out_path))
        assert Path(saved).exists()
        reopened = Image.open(saved)
        assert reopened.size == (64, 48)

    def test_jpeg_converts_rgba(self, tmp_path):
        from commands.overlay.register import _save_output
        from PIL import Image

        img = Image.new("RGBA", (64, 48), (10, 20, 30, 200))
        out_path = tmp_path / "out.jpg"
        _save_output(img, str(out_path))
        reopened = Image.open(out_path)
        assert reopened.mode == "RGB"
        assert reopened.size == (64, 48)


class TestOverlayCommand:
    def test_overlay_end_to_end(self, tmp_path):
        import importlib
        import json

        from click.testing import CliRunner
        from PIL import Image

        import cli.main as cli_mod

        importlib.reload(cli_mod)

        src = tmp_path / "src.png"
        Image.new("RGB", (200, 150), (40, 40, 40)).save(src)

        result = CliRunner().invoke(
            cli_mod.main,
            [
                "overlay",
                str(src),
                "--title",
                "Hello",
                "--overlay-effect",
                "box",
                "--overlay-bg",
                "red",
                "-F",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        # stderr (font warnings) may be mixed into output by the test runner;
        # real stdout is clean JSON, so extract from the first '{'.
        json_text = result.output[result.output.index("{") :]
        data = json.loads(json_text)
        assert Path(data["path"]).exists()
        assert data["width"] == 200
        assert data["height"] == 150
