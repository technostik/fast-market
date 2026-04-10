"""Twitter/X backend plugin."""

from __future__ import annotations

import warnings
from typing import Any

import tweepy

from plugins.base import SocialPlugin


class TwitterPlugin(SocialPlugin):
    """Plugin for posting to and searching on Twitter/X."""

    name = "twitter"

    def __init__(self, config: dict):
        self._config = config
        self._client: tweepy.Client | None = None
        self._client_v1: tweepy.API | None = None
        self._init_clients()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _init_clients(self) -> None:
        """Create tweepy.Client (v2) and optionally v1 API."""
        cfg = self._config
        # v2 is mandatory
        self._client = tweepy.Client(
            bearer_token=cfg.get("twitter_bearer_token", ""),
            consumer_key=cfg.get("twitter_api_key", ""),
            consumer_secret=cfg.get("twitter_api_secret", ""),
            access_token=cfg.get("twitter_access_token", ""),
            access_token_secret=cfg.get("twitter_access_token_secret", ""),
        )
        # v1 is optional, needed for media uploads
        if cfg.get("twitter_api_v1_enabled"):
            self._client_v1 = tweepy.API(
                tweepy.OAuth1UserHandler(
                    cfg.get("twitter_api_v1_consumer_key", ""),
                    cfg.get("twitter_api_v1_consumer_secret", ""),
                    cfg.get("twitter_api_v1_access_token", ""),
                    cfg.get("twitter_api_v1_access_token_secret", ""),
                )
            )
        else:
            self._client_v1 = None

    # ------------------------------------------------------------------
    # Post
    # ------------------------------------------------------------------
    def post(self, text: str, media: list[str] | None = None) -> dict:
        """Post a single tweet. Returns dict with id and url."""
        media_ids = None
        if media:
            if not self._client_v1:
                warnings.warn(
                    "Twitter v1 API is not enabled — media upload requires v1. "
                    "Enable 'twitter_api_v1_enabled' in your config. "
                    "Posting text-only."
                )
            else:
                media_ids = []
                for path in media:
                    uploaded = self._client_v1.media_upload(filename=path)
                    media_ids.append(uploaded.media_id)

        response = self._client.create_tweet(text=text, media_ids=media_ids)
        tweet_id = response.data["id"]
        # We can't easily get the username here without an extra call,
        # so we return the id and a URL template.
        return {
            "id": tweet_id,
            "status": "success",
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, max_results: int = 10, language: str = "en") -> list[dict]:
        """Search recent tweets matching *query*."""
        search_query = query
        if language:
            search_query = f"{query} lang:{language}"

        response = self._client.search_recent_tweets(
            query=search_query,
            max_results=max_results,
            tweet_fields=["author_id", "text", "created_at"],
            expansions=["author_id"],
            user_fields=["username", "name"],
        )

        results: list[dict] = []
        users_map = {u.id: u for u in response.includes.get("users", [])}
        for tweet in response.data or []:
            user = users_map.get(tweet.author_id)
            username = user.username if user else "unknown"
            results.append(
                {
                    "id": tweet.id,
                    "text": tweet.text,
                    "author": username,
                    "created_at": str(tweet.created_at) if tweet.created_at else None,
                    "url": f"https://twitter.com/{username}/status/{tweet.id}",
                }
            )
        return results
