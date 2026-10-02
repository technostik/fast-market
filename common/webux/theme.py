from __future__ import annotations

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

ALLOWED_VARS: frozenset[str] = frozenset(
    list(CANONICAL_VARS) + list(ALIASES.keys())
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
