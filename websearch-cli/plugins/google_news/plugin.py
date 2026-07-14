from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from common import structlog

from core.http import HttpTransport, Transport
from core.models import SearchItem
from core.text import strip_html
from plugins.base import SearchPlugin

logger = structlog.get_logger(__name__)


class GoogleNewsPlugin(SearchPlugin):
    name = "google_news"

    def __init__(self, config: dict[str, Any], transport: Transport | None = None) -> None:
        self.cfg = config.get(self.name, {}) or {}
        self.transport = transport or HttpTransport()

    @staticmethod
    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def _resolve(self, kwargs: dict) -> tuple[str, str]:
        language = kwargs.get("language") or self.cfg.get("language") or "fr"
        hl = kwargs.get("hl") or self.cfg.get("hl") or language
        gl = kwargs.get("gl") or self.cfg.get("gl") or language.upper()
        return hl, gl

    def search(self, query: str, limit: int, **kwargs) -> list[SearchItem]:
        hl, gl = self._resolve(kwargs)
        body = self.transport.get(
            "https://news.google.com/rss/search",
            params={"q": query, "hl": hl, "gl": gl},
            headers={"User-Agent": "fast-market-websearch/1.0"},
        )
        return self._parse(body, limit)

    def _parse(self, body: str, limit: int) -> list[SearchItem]:
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise RuntimeError(f"google_news: invalid RSS feed: {exc}") from exc

        items: list[SearchItem] = []
        for node in root.iter():
            if self._local(node.tag) != "item":
                continue
            fields: dict[str, str] = {}
            source_name = ""
            for child in node:
                local = self._local(child.tag)
                if local == "source":
                    source_name = (child.text or "").strip()
                    continue
                fields[local] = (child.text or "").strip()

            title = fields.get("title", "")
            # Google News titles end with " - <Source>"; drop the trailing source.
            if title.endswith(f" - {source_name}") and source_name:
                title = title[: -(len(source_name) + 3)].strip()

            items.append(
                SearchItem(
                    url=fields.get("link", ""),
                    title=title,
                    description=strip_html(fields.get("description", "")),
                    source=self.name,
                )
            )
            if len(items) >= limit:
                break
        logger.info("google_news_searched", count=len(items))
        return items
