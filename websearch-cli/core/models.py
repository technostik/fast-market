from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SearchItem:
    """A single web-search result.

    `source` is the plugin name (e.g. "google_news", "reddit", "hacker_news").
    """

    url: str
    title: str
    description: str
    source: str
