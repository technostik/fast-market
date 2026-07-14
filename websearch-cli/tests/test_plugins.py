from __future__ import annotations

from plugins.google_news.plugin import GoogleNewsPlugin
from plugins.hacker_news.plugin import HackerNewsPlugin
from plugins.reddit.plugin import RedditPlugin
from tests.fakes import FakeTransport

CONFIG = {
    "language": "fr",
    "limit": 10,
    "google_news": {"hl": "fr", "gl": "FR"},
    "reddit": {"user_agent": "test", "client_id": "", "client_secret": ""},
    "hacker_news": {"tags": "story"},
}


def test_google_news_parses_items():
    plugin = GoogleNewsPlugin(CONFIG, transport=FakeTransport())
    items = plugin.search("cats", limit=5)
    assert len(items) == 2
    assert items[0].source == "google_news"
    assert items[0].url == "https://example.com/cats"
    assert items[0].title == "Breaking news about cats"  # trailing " - Example News" stripped
    assert "taking over the internet" in items[0].description


def test_reddit_parses_items_and_fixes_relative_url():
    plugin = RedditPlugin(CONFIG, transport=FakeTransport())
    items = plugin.search("tips", limit=5)
    assert len(items) == 2
    assert items[0].source == "reddit"
    assert items[0].url.startswith("https://reddit.com/")
    # relative permalink should be absolutized
    assert items[1].url.startswith("https://www.reddit.com/r/news/comments/xyz")


def test_hacker_news_parses_items_and_builds_item_url():
    plugin = HackerNewsPlugin(CONFIG, transport=FakeTransport())
    items = plugin.search("tool", limit=5)
    assert len(items) == 2
    assert items[0].source == "hacker_news"
    assert items[0].url == "https://showhn.example.com"
    # null url -> HN item url
    assert "news.ycombinator.com/item?id=222" in items[1].url


def test_hacker_news_points_filter():
    plugin = HackerNewsPlugin(CONFIG, transport=FakeTransport())
    items = plugin.search("tool", limit=5, points=20)
    assert len(items) == 1
    assert items[0].title == "Show HN: A new tool"
