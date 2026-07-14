from __future__ import annotations

import json
from typing import Any

import httpx

from common import structlog

from core.http import HttpTransport, Transport
from core.models import SearchItem
from plugins.base import SearchPlugin

logger = structlog.get_logger(__name__)

_BASE = "https://www.reddit.com"


class RedditPlugin(SearchPlugin):
    name = "reddit"

    def __init__(self, config: dict[str, Any], transport: Transport | None = None) -> None:
        self.cfg = config.get(self.name, {}) or {}
        self.transport = transport or HttpTransport()

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": self.cfg.get("user_agent", "fast-market-websearch/1.0")}
        client_id = self.cfg.get("client_id")
        client_secret = self.cfg.get("client_secret")
        if client_id and client_secret:
            import base64

            token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        return headers

    def search(self, query: str, limit: int, **kwargs) -> list[SearchItem]:
        subreddit = kwargs.get("subreddit") or self.cfg.get("subreddit") or ""
        sort = kwargs.get("sort") or "relevance"

        if subreddit:
            url = f"{_BASE}/r/{subreddit}/search.json"
            params = {"q": query, "restrict_sr": "on", "sort": sort, "limit": limit}
        else:
            url = f"{_BASE}/search.json"
            params = {"q": query, "sort": sort, "limit": limit}

        body = self.transport.get(url, params=params, headers=self._headers())
        return self._parse(body, limit)

    def _parse(self, body: str, limit: int) -> list[SearchItem]:
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"reddit: invalid JSON response: {exc}") from exc

        children = data.get("data", {}).get("children", [])
        items: list[SearchItem] = []
        for child in children:
            d = child.get("data", {})
            url = d.get("url", "")
            if not url or url.startswith("/"):
                url = f"{_BASE}{d.get('permalink', '')}"
            description = d.get("selftext") or ""
            items.append(
                SearchItem(
                    url=url,
                    title=d.get("title", ""),
                    description=description,
                    source=self.name,
                )
            )
            if len(items) >= limit:
                break
        logger.info("reddit_searched", count=len(items))
        return items
