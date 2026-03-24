from __future__ import annotations

import hashlib
import re


def make_handle(source_plugin: str, source_id: str, title: str) -> str:
    """
    Generate a stable, human-friendly handle for a document.

    Format: {plugin_prefix}-{title_slug}-{hash4}
    Example: yt-my-video-title-a3f2
             ob-how-to-use-obsidian-7c1e

    Rules:
    - Deterministic: same inputs always produce the same handle
    - Collision-resistant: 4-char hex suffix from sha256(plugin+source_id)
    - URL/shell safe: lowercase alphanumeric + hyphens only
    - Max 64 chars total
    """
    prefix = {"youtube": "yt", "obsidian": "ob"}.get(source_plugin, source_plugin[:2])
    slug = _slugify(title)[:48]
    suffix = hashlib.sha256(f"{source_plugin}:{source_id}".encode()).hexdigest()[:4]
    return f"{prefix}-{slug}-{suffix}" if slug else f"{prefix}-{suffix}"


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text
