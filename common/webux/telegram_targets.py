"""Telegram target listing/discovery for the webux publish plugins.

The publish plugins must not depend on ``python-telegram-bot``: they read the
targets from the profile's ``message`` config and delegate discovery to the
``message`` CLI through a subprocess.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import os
import shutil
from typing import Any

from common.core.config import load_tool_config
from common.message_targets import TargetError, list_targets

#: Alert text used when a profile has no ``*_telegram_alert_template``.
DEFAULT_SHORT_ALERT_TEMPLATE = "✅ Short publié : {title}\n{url}"
DEFAULT_LONG_ALERT_TEMPLATE = "✅ Vidéo publiée : {title}\n{url}"


@contextlib.contextmanager
def _profile_env(profile: str | None):
    """Temporarily target ``profile`` for synchronous config loading."""
    old = os.environ.get("FASTMARKET_PROFILE")
    if profile:
        os.environ["FASTMARKET_PROFILE"] = profile
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("FASTMARKET_PROFILE", None)
        else:
            os.environ["FASTMARKET_PROFILE"] = old


def load_telegram_targets(profile: str | None = None) -> dict[str, Any]:
    """Return the telegram targets of ``profile`` (default: active profile)."""
    try:
        with _profile_env(profile):
            cfg = load_tool_config("message")
    except Exception as exc:
        raise RuntimeError(f"Could not load the message config: {exc}") from exc
    tg = cfg.get("telegram", {}) if isinstance(cfg, dict) else {}
    if not isinstance(tg, dict):
        raise RuntimeError("telegram config section must be a mapping")
    try:
        rows = list_targets(tg)
    except TargetError as exc:
        raise RuntimeError(str(exc)) from exc
    return {
        "targets": rows,
        "default": str(tg.get("default_target") or ""),
    }


async def discover_telegram_targets(
    profile: str | None = None, timeout: float = 60.0
) -> dict[str, Any]:
    """Run ``message targets discover`` for ``profile`` and parse its JSON."""
    exe = shutil.which("message") or "message"
    env = os.environ.copy()
    if profile:
        env["FASTMARKET_PROFILE"] = profile
    proc = await asyncio.create_subprocess_exec(
        exe,
        "targets",
        "discover",
        "--format",
        "json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(
            f"'message targets discover' timed out after {timeout:.0f}s"
        ) from None

    if proc.returncode != 0:
        err = (stderr or b"").decode(errors="replace").strip()
        raise RuntimeError(err or f"message targets discover exited {proc.returncode}")

    raw = (stdout or b"").decode(errors="replace").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"Unexpected discovery output: {raw[:200]!r}")
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid discovery JSON: {exc}") from exc


def render_alert(
    template: str | None,
    *,
    default: str,
    title: str = "",
    url: str = "",
    video_id: str = "",
) -> str:
    """Render a publish alert from a per-profile template.

    Placeholders are replaced literally (``{title}``, ``{url}``, ``{video_id}``)
    instead of through ``str.format``: a stray brace or an unknown placeholder
    in a user-written message must never crash a publish. ``title`` and ``url``
    are HTML-escaped because ``message alert`` runs with ``parse_mode=HTML``;
    the template itself may contain markup (``<b>``, ``<a href>``…).

    An empty/blank template falls back to ``default`` (the historical text).
    """
    tpl = (template or "").strip() or default
    safe_title = html.escape((title or "").strip() or (video_id or ""))
    return (
        tpl.replace("{title}", safe_title)
        .replace("{url}", html.escape(url or ""))
        .replace("{video_id}", html.escape(video_id or ""))
    )
