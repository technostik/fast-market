from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import feedparser
import requests

from plugins.base import SourcePlugin, ItemMetadata


class RSSPlugin(SourcePlugin):
    name = "rss"

    async def fetch_new_items(
        self,
        last_item_id: str | None = None,
        limit: int = 50,
        force: bool = False,
        seen_item_ids: set[str] | None = None,
        date_filter: str | None = None,
    ) -> list[ItemMetadata]:
        if not self._should_fetch(force):
            return []

        rss_url = self.source_config["origin"]
        feed = feedparser.parse(rss_url)

        if hasattr(feed, "bozo_exception") and feed.bozo_exception:
            exc = feed.bozo_exception
            exc_details = str(exc)
            if hasattr(exc, "getLineNumber"):
                exc_details += f" (line {exc.getLineNumber()}, col {exc.getColumnNumber()})"

            raw_excerpt = "(unable to fetch raw content)"
            try:
                resp = requests.get(
                    rss_url,
                    timeout=10,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; monitor-agent/1.0)"},
                )
                if resp.status_code == 200:
                    raw_excerpt = resp.text[:500].replace("\n", " ").strip()
                else:
                    raw_excerpt = f"(HTTP {resp.status_code}, content-type: {resp.headers.get('content-type', 'unknown')})"
            except Exception:
                pass

            raise Exception(
                f"RSS feed parsing error: {exc_details}\n"
                f"URL: {rss_url}\n"
                f"Content excerpt: {raw_excerpt}"
            )

        today = None
        if date_filter == "today":
            today = datetime.now(timezone.utc).date()

        items = []
        for entry in feed.entries[:limit]:
            categories = []
            if hasattr(entry, "tags"):
                categories = [tag.term for tag in entry.tags]

            content = entry.get("content", [{}])[0].get("value", "")
            if not content and hasattr(entry, "summary"):
                content = entry.summary
            word_count = len(content.split())

            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime.fromtimestamp(
                    time.mktime(entry.published_parsed), tz=timezone.utc
                )
            else:
                published = datetime.now(timezone.utc)

            if last_item_id and entry.id == last_item_id:
                break

            item = ItemMetadata(
                id=entry.id,
                title=entry.title,
                url=entry.link,
                published_at=published,
                content_type="article",
                source_plugin=self.name,
                source_id=self.source_config.get("id", ""),
                extra={
                    "author": entry.get("author", ""),
                    "categories": categories,
                    "word_count": word_count,
                    "feed_title": feed.feed.get("title", "") if hasattr(feed, "feed") else "",
                },
            )

            if today and item.published_at.date() != today:
                continue

            items.append(item)

        return items

    def validate_identifier(self, identifier: str) -> bool:
        return identifier.startswith(("http://", "https://")) and (
            "rss" in identifier.lower()
            or "feed" in identifier.lower()
            or "atom" in identifier.lower()
        )

    def get_identifier_display(self, identifier: str) -> str:
        try:
            feed = feedparser.parse(identifier)
            if feed.feed and hasattr(feed.feed, "title"):
                return feed.feed.title
        except:
            pass
        return identifier
