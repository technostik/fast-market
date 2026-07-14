from __future__ import annotations

import json
from typing import Any

from common import structlog

from core.http import HttpTransport, Transport
from core.models import SearchItem
from plugins.base import SearchPlugin

logger = structlog.get_logger(__name__)

_BASE = "https://hn.algolia.com/api/v1/search"


class HackerNewsPlugin(SearchPlugin):
    name = "hacker_news"

    def __init__(self, config: dict[str, Any], transport: Transport | None = None) -> None:
        self.cfg = config.get(self.name, {}) or {}
        self.transport = transport or HttpTransport()

    def search(self, query: str, limit: int, **kwargs) -> list[SearchItem]:
        tags = kwargs.get("tags") or self.cfg.get("tags") or "story"
        min_points = int(kwargs.get("points") or self.cfg.get("points") or 0)

        body = self.transport.get(
            _BASE,
            params={"query": query, "tags": tags, "hitsPerPage": limit},
            headers={"User-Agent": "fast-market-websearch/1.0"},
        )
        return self._parse(body, limit, min_points)

    def _parse(self, body: str, limit: int, min_points: int) -> list[SearchItem]:
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"hacker_news: invalid JSON response: {exc}") from exc

        hits = data.get("hits", [])
        items: list[SearchItem] = []
        for hit in hits:
            points = int(hit.get("points") or 0)
            if min_points and points < min_points:
                continue

            url = hit.get("url") or ""
            if not url:
                url = f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"

            description = hit.get("story_text") or hit.get("comment_text") or ""
            items.append(
                SearchItem(
                    url=url,
                    title=hit.get("title") or "",
                    description=description,
                    source=self.name,
                )
            )
            if len(items) >= limit:
                break
        logger.info("hacker_news_searched", count=len(items))
        return items
