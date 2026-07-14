from __future__ import annotations

from core.http import Transport

_GOOGLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Breaking news about cats - Example News</title>
      <link>https://example.com/cats</link>
      <description>&lt;p&gt;Cats are taking over the internet.&lt;/p&gt;</description>
      <source url="https://example.com">Example News</source>
    </item>
    <item>
      <title>Another story - Other Source</title>
      <link>https://other.com/story</link>
      <description>&lt;p&gt;More text here.&lt;/p&gt;</description>
      <source url="https://other.com">Other Source</source>
    </item>
  </channel>
</rss>"""

_REDDIT_JSON = """{
  "data": {
    "children": [
      {"data": {"title": "Reddit post one", "url": "https://reddit.com/r/aww/comments/abc", "selftext": "A cute thread."}},
      {"data": {"title": "Reddit post two", "url": "/r/news/comments/xyz", "permalink": "/r/news/comments/xyz", "selftext": ""}}
    ]
  }
}"""

_HN_JSON = """{
  "hits": [
    {"objectID": "111", "title": "Show HN: A new tool", "url": "https://showhn.example.com", "story_text": "", "points": 42},
    {"objectID": "222", "title": "Ask HN: Best practices", "url": "", "story_text": "What are your tips?", "points": 10}
  ]
}"""


class FakeTransport(Transport):
    """Returns canned responses keyed by a URL substring matcher."""

    ROUTES = {
        "news.google.com": _GOOGLE_RSS,
        "reddit.com": _REDDIT_JSON,
        "hn.algolia.com": _HN_JSON,
    }

    def get(self, url: str, *, params=None, headers=None) -> str:
        for key, body in self.ROUTES.items():
            if key in url:
                return body
        raise AssertionError(f"FakeTransport: no route for {url}")
