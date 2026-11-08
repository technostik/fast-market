"""Unified webux theme definitions.

Single source of truth for CSS custom properties used by the webux hub
(``webux-cli/core/server.py``) and every plugin page.

Canonical variables (use these in all new plugin HTML/CSS):

  --bg, --bg-secondary, --bg3, --surface, --surface2,
  --text, --text-dim, --text-muted,
  --accent, --accent2,
  --success, --error, --warning, --orange,
  --border, --link, --link-hover, --info

Legacy aliases (kept for backwards compatibility with out-of-tree plugins
such as monitor/corpus, and during migration):

  --bg2      -> --bg-secondary
  --dim      -> --text-dim
  --ok/--green    -> --success
  --err/--red     -> --error
  --warn/--yellow -> --warning
  --bg-dim   -> --bg3
"""

from __future__ import annotations

import colorsys
import hashlib

DEFAULT_THEME = "dark"

THEME_NAMES: tuple[str, ...] = ("dark", "light", "blue")

# CodeMirror editor theme per webux theme (user asked: flip editor with theme).
CODEMIRROR_THEMES: dict[str, str] = {
    "dark": "dracula",
    "light": "default",
    "blue": "dracula",
}

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "--bg": "#1a1a2e",
        "--bg-secondary": "#16213e",
        "--bg3": "#0f172a",
        "--surface": "#1d2a4a",
        "--surface2": "#26395f",
        "--text": "#eee",
        "--text-dim": "#888",
        "--text-muted": "#9aa0b4",
        "--accent": "#0f3460",
        "--accent2": "#7dd3fc",
        "--success": "#4ade80",
        "--error": "#f87171",
        "--warning": "#fbbf24",
        "--orange": "#fab387",
        "--border": "#333",
        "--link": "#7dd3fc",
        "--link-hover": "#bae6fd",
        "--info": "#38bdf8",
    },
    "light": {
        "--bg": "#ffffff",
        "--bg-secondary": "#f1f5f9",
        "--bg3": "#e2e8f0",
        "--surface": "#e8eef5",
        "--surface2": "#cbd5e1",
        "--text": "#0f172a",
        "--text-dim": "#64748b",
        "--text-muted": "#64748b",
        "--accent": "#2563eb",
        "--accent2": "#0284c7",
        "--success": "#16a34a",
        "--error": "#dc2626",
        "--warning": "#d97706",
        "--orange": "#ea580c",
        "--border": "#cbd5e1",
        "--link": "#2563eb",
        "--link-hover": "#1d4ed8",
        "--info": "#0284c7",
    },
    "blue": {
        "--bg": "#0b1d3a",
        "--bg-secondary": "#102a56",
        "--bg3": "#081426",
        "--surface": "#14305e",
        "--surface2": "#1e4179",
        "--text": "#e8f1ff",
        "--text-dim": "#8ea6c8",
        "--text-muted": "#a9bede",
        "--accent": "#3b82f6",
        "--accent2": "#60a5fa",
        "--success": "#4ade80",
        "--error": "#f87171",
        "--warning": "#fbbf24",
        "--orange": "#fab387",
        "--border": "#274a7d",
        "--link": "#7dd3fc",
        "--link-hover": "#bae6fd",
        "--info": "#7dd3fc",
    },
}

# Legacy alias -> canonical variable.
ALIASES: dict[str, str] = {
    "--bg2": "--bg-secondary",
    "--bg-dim": "--bg3",
    "--dim": "--text-dim",
    "--ok": "--success",
    "--green": "--success",
    "--err": "--error",
    "--red": "--error",
    "--warn": "--warning",
    "--yellow": "--warning",
}

CANONICAL_VARS: frozenset[str] = frozenset(
    [
        "--bg",
        "--bg-secondary",
        "--bg3",
        "--surface",
        "--surface2",
        "--text",
        "--text-dim",
        "--text-muted",
        "--accent",
        "--accent2",
        "--success",
        "--error",
        "--warning",
        "--orange",
        "--border",
        "--link",
        "--link-hover",
        "--info",
    ]
)

#
# Per-profile tones
#
# Every profile (a persona/YouTube channel namespace) gets a distinct dark
# background tone, so the toolbar, the publish components and each pipeline
# row can paint themselves with the active channel's colour. Tones are always
# dark (lightness 0.13-0.74) with a light foreground, so they stay readable
# under every webux theme.
#
# Assignment:
#   1. an explicit ``profile_colors`` map from the webux tool config
#      (``webux setup profile-color set``), then
#   2. evenly spaced hues over the *sorted* profile list, so two profiles are
#      ~180 deg apart, three ~120 deg, etc. (maximal contrast — a name hash can
#      hand two profiles near-identical blue/green hues).

PROFILE_VARS: frozenset[str] = frozenset(
    [
        "--profile-bg",
        "--profile-bg-soft",
        "--profile-border",
        "--profile-accent",
        "--profile-text",
        "--profile-dim",
    ]
)

#: Hue (degrees) of the first profile in the sorted list; the rest follow an
#: even step around the wheel.
PROFILE_HUE_OFFSET = 205.0

#: Neutral fallback when a name is empty or unknown.
DEFAULT_PROFILE_TONE: dict[str, str] = {
    "bg": "#1a1a2e",
    "bg_soft": "#22223c",
    "border": "#3a3a5c",
    "accent": "#7dd3fc",
    "text": "#f5f7fa",
    "dim": "#b6bfd0",
}


def _hsl_hex(hue: float, sat: float, light: float) -> str:
    """HSL (h in [0,1)) -> '#rrggbb'."""
    r, g, b = colorsys.hls_to_rgb(hue % 1.0, light, sat)
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, round(r * 255))),
        max(0, min(255, round(g * 255))),
        max(0, min(255, round(b * 255))),
    )


def _parse_hex(color: str) -> tuple[float, float, float] | None:
    """Parse '#rgb'/'#rrggbb' to (r,g,b) floats in [0,1], else None."""
    if not isinstance(color, str):
        return None
    h = color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _tone_for_hue(hue: float) -> dict[str, str]:
    """A full dark tone dict from a hue in [0,1)."""
    return {
        "bg": _hsl_hex(hue, 0.30, 0.13),
        "bg_soft": _hsl_hex(hue, 0.28, 0.18),
        "border": _hsl_hex(hue, 0.26, 0.30),
        "accent": _hsl_hex(hue, 0.60, 0.52),
        "text": "#f5f7fa",
        "dim": _hsl_hex(hue, 0.16, 0.74),
    }


def is_valid_profile_color(color: str) -> bool:
    """True for '#rgb' / '#rrggbb' (the only accepted profile colour form)."""
    return _parse_hex(color) is not None


def tone_from_color(color: str) -> dict[str, str]:
    """Derive a full tone from an explicit colour (background wins)."""
    rgb = _parse_hex(color)
    if rgb is None:
        return dict(DEFAULT_PROFILE_TONE)
    h, light, s = colorsys.rgb_to_hls(*rgb)
    return {
        "bg": "#" + "".join(f"{round(c * 255):02x}" for c in rgb),
        "bg_soft": _hsl_hex(h, min(1.0, s * 0.9 + 0.05), min(0.45, light + 0.06)),
        "border": _hsl_hex(h, min(1.0, s * 0.9 + 0.05), min(0.65, light + 0.16)),
        "accent": _hsl_hex(h, min(1.0, max(0.45, s)), 0.58),
        "text": "#f5f7fa",
        "dim": _hsl_hex(h, 0.16, 0.76),
    }


def profile_tone(name: str | None) -> dict[str, str]:
    """Return a deterministic tone for a *single* profile name.

    Fallback for callers that do not know the full profile list. The hub uses
    :func:`profile_tones` instead, which spaces hues evenly for contrast.
    Stable across processes (SHA-1, not Python's randomised ``hash``).
    """
    if not name:
        return dict(DEFAULT_PROFILE_TONE)
    digest = hashlib.sha1(str(name).encode("utf-8")).digest()
    hue = (int.from_bytes(digest[:4], "big") % 3600) / 3600.0
    return _tone_for_hue(hue)


def profile_tones(
    names: list[str] | tuple[str, ...],
    overrides: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    """Assign a maximally contrasting tone to every profile in ``names``.

    ``overrides`` maps a profile name to an explicit ``#rrggbb`` colour; those
    win over the even-hue assignment.
    """
    overrides = overrides or {}
    ordered = sorted({n for n in names if n})
    total = len(ordered)
    tones: dict[str, dict[str, str]] = {}
    for index, name in enumerate(ordered):
        explicit = overrides.get(name)
        if isinstance(explicit, str) and _parse_hex(explicit) is not None:
            tones[name] = tone_from_color(explicit)
            continue
        hue = ((PROFILE_HUE_OFFSET + index * (360.0 / total)) % 360.0) / 360.0
        tones[name] = _tone_for_hue(hue)
    return tones


def render_profile_css(
    profiles: list[str] | tuple[str, ...] | dict[str, dict[str, str]],
) -> str:
    """Render ``[data-profile="<name>"]`` rules for every known profile.

    Accepts either a list of names (tones are computed) or a ready tone map
    from :func:`profile_tones`.
    """
    tones = profiles if isinstance(profiles, dict) else profile_tones(profiles)
    rules: list[str] = []
    for name, tone in tones.items():
        # Only slug-safe names can be embedded in a selector unquoted-escaped.
        if not name or not all(c.isalnum() or c in "-_" for c in name):
            continue
        rules.append(
            f'[data-profile="{name}"] {{\n'
            f"  --profile-bg: {tone['bg']};\n"
            f"  --profile-bg-soft: {tone['bg_soft']};\n"
            f"  --profile-border: {tone['border']};\n"
            f"  --profile-accent: {tone['accent']};\n"
            f"  --profile-text: {tone['text']};\n"
            f"  --profile-dim: {tone['dim']};\n"
            "}"
        )
    return "\n".join(rules)


ALLOWED_VARS: frozenset[str] = frozenset(
    list(CANONICAL_VARS) + list(ALIASES.keys()) + list(PROFILE_VARS)
)


def is_valid_theme(name: str | None) -> bool:
    return (name or "") in THEMES


def resolve_theme(config: dict | None, override: str | None = None) -> str:
    """Resolve effective theme: explicit override > config > default.

    Unknown names fall back to DEFAULT_THEME (never raises).
    """
    if override and override in THEMES:
        return override
    if isinstance(config, dict):
        configured = config.get("theme")
        if isinstance(configured, str) and configured in THEMES:
            return configured
    if isinstance(override, str) and override:
        # Unknown override requested: fall back loudly to default.
        return DEFAULT_THEME
    return DEFAULT_THEME


def theme_vars(name: str) -> dict[str, str]:
    """Return canonical vars for a theme, falling back to default."""
    return dict(THEMES.get(name, THEMES[DEFAULT_THEME]))


def _block_for_theme(name: str) -> str:
    vars_ = theme_vars(name)
    lines = [f"  {k}: {v};" for k, v in sorted(vars_.items())]
    # Emit legacy aliases so old plugin HTML keeps working during/after migration.
    for alias in sorted(ALIASES):
        canonical = ALIASES[alias]
        if canonical in vars_:
            lines.append(f"  {alias}: var({canonical});")
    body = "\n".join(lines)
    if name == DEFAULT_THEME:
        return f":root {{\n{body}\n}}\n[data-theme=\"{name}\"] {{\n{body}\n}}"
    return f"[data-theme=\"{name}\"] {{\n{body}\n}}"


def render_all_themes_css() -> str:
    """Render :root (dark default) + per-theme overrides for client-side switching."""
    return "\n".join(_block_for_theme(name) for name in THEME_NAMES)


def render_root_css(name: str) -> str:
    """Render CSS for a single theme (used by tests / /theme.css?theme=x)."""
    return _block_for_theme(name if name in THEMES else DEFAULT_THEME)


def codemirror_theme(name: str) -> str:
    return CODEMIRROR_THEMES.get(name, CODEMIRROR_THEMES[DEFAULT_THEME])


# ---------------------------------------------------------------------------
# Contrast helpers (used by regression tests to catch unreadable themes)
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (r, g, b)


def _luminance(hex_color: str) -> float:
    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(hex_color)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(bg_hex: str, fg_hex: str) -> float:
    """WCAG contrast ratio between two hex colors."""
    l1 = _luminance(bg_hex)
    l2 = _luminance(fg_hex)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)
