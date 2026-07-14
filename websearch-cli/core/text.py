from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Remove HTML tags and decode entities, collapsing whitespace."""
    if not text:
        return ""
    cleaned = _TAG_RE.sub(" ", text)
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()
