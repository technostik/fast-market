from __future__ import annotations

import functools
import math
import os
import re
from typing import Tuple

from PIL import Image, ImageColor, ImageDraw, ImageFont

from core.models import TextOverlayConfig

# Where we look for font files when a family name is requested.
_FONT_SEARCH_DIRS = [
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"),
    os.path.expanduser("~/.local/share/fonts"),
]

RGB = Tuple[int, int, int]
RGBA = Tuple[int, int, int, int]

_HEX_RE = re.compile(r"^([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$")


def resolve_color(name: str | None) -> RGB | None:
    """Resolve a color name/hex into an (R, G, B) tuple.

    Accepted forms (case-insensitive):
      - X11 names, spaces normalized (``"light green"`` -> ``lightgreen``)
      - ``#rrggbb`` / ``#rgb`` / ``#rrggbbaa`` (must be quoted in YAML, see note)
      - ``0xrrggbb`` / ``0xrgb`` (safe to use unquoted in YAML)
      - bare ``rrggbb`` / ``rgb`` (safe to use unquoted in YAML)

    ``"none"`` / ``"transparent"`` / empty -> ``None`` (disables the effect).
    """
    if name is None:
        return None
    if isinstance(name, int):
        # YAML parses 0x... literals as integers
        name = f"{name:06x}"
    normalized = name.strip().lower()
    if normalized in ("", "none", "transparent"):
        return None

    # Hex forms (strip leading # or 0x so they work unquoted in YAML too)
    hex_candidate = normalized.removeprefix("#").removeprefix("0x")
    if _HEX_RE.match(hex_candidate):
        if len(hex_candidate) == 3:
            h = "".join(c * 2 for c in hex_candidate)
        elif len(hex_candidate) == 8:
            h = hex_candidate[:6]
        else:
            h = hex_candidate
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    # X11 / named colors
    compact = normalized.replace(" ", "")
    for candidate in (compact, normalized):
        try:
            rgb = ImageColor.getrgb(candidate)
        except ValueError:
            continue
        return (rgb[0], rgb[1], rgb[2])
    return None


@functools.lru_cache(maxsize=32)
def _find_font_file(family: str) -> str | None:
    """Locate a font file whose name contains the requested family."""
    family_l = family.lower()
    for base in _FONT_SEARCH_DIRS:
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fname in files:
                if fname.lower().endswith((".ttf", ".otf", ".ttc")) and family_l in fname.lower():
                    return os.path.join(root, fname)
    return None


def _variant_family(family: str, style: str) -> str:
    """Return the font family name for a given style variant."""
    s = (style or "normal").lower().replace(" ", "-")
    if s in ("bold",):
        return f"{family}-Bold"
    if s in ("italic", "oblique"):
        return f"{family}-Italic"
    if s in ("bold-italic", "bolditalic", "bold-oblique"):
        return f"{family}-BoldItalic"
    return family


def load_font(family: str, size: int, style: str = "normal") -> ImageFont.ImageFont:
    """Load a truetype font (with style variant), falling back gracefully.

    Tries, in order: the styled family name, the base family name, the
    DejaVuSans fallback, then PIL's default bitmap font.
    """
    candidates = [_variant_family(family, style), family, "DejaVuSans"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, IOError):
            pass
        path = _find_font_file(candidate)
        if path:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                pass
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    """Greedy word-wrap, preserving explicit newlines."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        line = ""
        for word in words:
            candidate = (line + " " + word).strip()
            if not line or draw.textlength(candidate, font=font) <= max_width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _fit_font_size(
    text: str,
    family: str,
    img_w: int,
    img_h: int,
    draw: ImageDraw.ImageDraw,
    style: str = "normal",
    max_w_ratio: float = 0.9,
    max_h_ratio: float = 0.4,
) -> tuple[int, list[str]]:
    """Binary-search the largest font size that fits the text in the budget."""
    max_w = int(img_w * max_w_ratio)
    max_h = int(img_h * max_h_ratio)

    def measure(size: int) -> tuple[int, int, list[str]]:
        font = load_font(family, size, style)
        lines = _wrap_text(draw, text, font, max_w)
        width = max((draw.textlength(ln, font=font) for ln in lines), default=0)
        ascent, descent = font.getmetrics()
        height = len(lines) * (ascent + descent)
        return int(width), int(height), lines

    lo, hi, best = 8, max(8, img_h), 8
    best_lines: list[str] = []
    while lo <= hi:
        mid = (lo + hi) // 2
        width, height, lines = measure(mid)
        if width <= max_w and height <= max_h:
            best, best_lines = mid, lines
            lo = mid + 1
        else:
            hi = mid - 1
    if not best_lines:
        best_lines = _wrap_text(draw, text, load_font(family, best, style), max_w)
    return best, best_lines


def _block_metrics(vpos: str, hpos: str, img_w: int, img_h: int, block_w: int, block_h: int, pad: int) -> tuple[int, int]:
    """Return the top-left (x, y) of the text block given alignment."""
    margin = max(8, int(min(img_w, img_h) * 0.03))
    if hpos == "left":
        x = margin
    elif hpos == "right":
        x = img_w - block_w - margin
    else:
        x = (img_w - block_w) // 2

    if vpos == "top":
        y = margin
    elif vpos == "middle":
        y = (img_h - block_h) // 2
    else:
        y = img_h - block_h - margin

    return x - pad, y - pad


def _draw_band(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], bg: RGB, peak: int = 200) -> None:
    """Draw a full-width horizontal band with a Gaussian (reverse-U) alpha curve."""
    x0, y0, x1, y1 = rect
    height = y1 - y0
    if height <= 0:
        return
    sigma = 0.45  # controls falloff; edges reach ~8% of peak
    for i in range(height):
        yy = y0 + i
        d = (i + 0.5 - height / 2) / (height / 2)  # -1 at top edge, +1 at bottom edge
        alpha = int(peak * math.exp(-(d * d) / (2 * sigma * sigma)))
        if alpha <= 0:
            continue
        draw.line([(x0, yy), (x1, yy)], fill=(bg[0], bg[1], bg[2], alpha))


def apply_text_overlay(
    image: Image.Image,
    cfg: TextOverlayConfig,
    font_family: str | None = None,
    font_style: str | None = None,
) -> Image.Image:
    """Superimpose ``cfg.text`` onto ``image`` and return a new image.

    Effects are drawn using the background color (``cfg.bg``); when ``bg``
    resolves to ``None`` the background effect is skipped.
    """
    if not cfg.enabled or not cfg.text:
        return image

    family = font_family or "Tomorrow"
    style = font_style or cfg.style or "normal"
    img_w, img_h = image.size
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    max_w = int(img_w * 0.95)
    if cfg.size == "fit" or not str(cfg.size).isdigit():
        font_size, lines = _fit_font_size(cfg.text, family, img_w, img_h, draw, style)
    else:
        font_size = int(cfg.size)
        font = load_font(family, font_size, style)
        lines = _wrap_text(draw, cfg.text, font, max_w)

    font = load_font(family, font_size, style)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    block_w = max((draw.textlength(ln, font=font) for ln in lines), default=0)
    block_h = line_height * len(lines)

    pad = max(6, int(font_size * 0.25))
    x, y = _block_metrics(cfg.vpos, cfg.hpos, img_w, img_h, int(block_w), block_h, pad)

    fg = resolve_color(cfg.fg)
    bg = resolve_color(cfg.bg)
    fg_color: RGBA = (fg[0], fg[1], fg[2], 255) if fg else (255, 255, 255, 255)

    effect = (cfg.effect or "none").lower()
    rect = (x, y, x + int(block_w) + 2 * pad, y + block_h + 2 * pad)

    if effect == "box" and bg is not None:
        draw.rectangle(rect, fill=(bg[0], bg[1], bg[2], 200))
    elif effect == "band" and bg is not None:
        band_h = max(1, int(img_h * max(1, cfg.band_size) / 100))
        block_cy = y + pad + block_h / 2
        band_rect = (
            0,
            int(block_cy - band_h / 2),
            img_w,
            int(block_cy + band_h / 2),
        )
        _draw_band(draw, band_rect, bg, peak=200)
    elif effect == "shadow" and bg is not None:
        for i, line in enumerate(lines):
            ly = y + pad + i * line_height
            draw.text(
                (x + pad, ly),
                line,
                font=font,
                fill=fg_color,
                stroke_width=max(1, font_size // 10),
                stroke_fill=(bg[0], bg[1], bg[2], 255),
            )

    if effect != "shadow":
        for i, line in enumerate(lines):
            ly = y + pad + i * line_height
            draw.text((x + pad, ly), line, font=font, fill=fg_color)

    combined = Image.alpha_composite(base, overlay)
    if image.mode != "RGBA":
        combined = combined.convert(image.mode)
    return combined
