"""Substack backend plugin.

Uses the ``substack`` Python package (unofficial API) with Selenium-based
cookie authentication as a fallback when cookies expire.
"""

from __future__ import annotations

import json
import os
import re
import time
import warnings
from typing import Any

from plugins.base import SocialPlugin


class SubstackPlugin(SocialPlugin):
    """Plugin for posting to Substack.

    Note: Substack has no official public API. This plugin uses the
    unofficial ``substack`` Python package with Selenium-based auth.
    Searching is **not** available — the backend raises a warning.
    """

    name = "substack"

    def __init__(self, config: dict):
        self._config = config
        self.email = config.get("substack_email", "")
        self.password = config.get("substack_password", "")
        publication_urls_raw = config.get("substack_publication_url", "")
        if isinstance(publication_urls_raw, str):
            self.publication_urls = [
                u.strip() for u in publication_urls_raw.split(";") if u.strip()
            ]
        else:
            self.publication_urls = publication_urls_raw

        self.cookies_base_path = "substack_cookies"
        self.selenium_cookies_base_path = "selenium_cookies"
        self.api = None
        self.api_instances: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Internal helpers — auth
    # ------------------------------------------------------------------
    def _get_cookies_paths(self, publication_url: str) -> tuple[str, str]:
        safe_url = re.sub(r"[^\w\-]", "_", publication_url)
        return (
            f"{self.cookies_base_path}_{safe_url}.json",
            f"{self.selenium_cookies_base_path}_{safe_url}.json",
        )

    def _renew_cookie(self, publication_url: str) -> None:
        """Log in via Selenium and persist cookies."""
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        chrome_options = Options()
        chrome_options.add_argument("--start-maximized")
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)

        try:
            driver.get("https://substack.com/sign-in")
            wait = WebDriverWait(driver, 20)
            email_field = wait.until(EC.presence_of_element_located((By.NAME, "email")))
            email_field.send_keys(self.email)

            sign_in_link = wait.until(
                EC.element_to_be_clickable((By.LINK_TEXT, "Sign in with password"))
            )
            sign_in_link.click()

            password_field = wait.until(
                EC.presence_of_element_located((By.NAME, "password"))
            )
            password_field.send_keys(self.password)
            password_field.send_keys(Keys.RETURN)

            time.sleep(5)
            cookies = driver.get_cookies()
            _, selenium_cookies_path = self._get_cookies_paths(publication_url)
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            with open(selenium_cookies_path, "w") as f:
                json.dump(cookie_dict, f)
        finally:
            driver.quit()

    def _initialize_api(self, publication_url: str | None = None, force: bool = False) -> None:
        from substack import Api

        publication_url = publication_url or self.publication_urls[0]
        if publication_url in self.api_instances and not force:
            self.api = self.api_instances[publication_url]
            return

        _, selenium_cookies_path = self._get_cookies_paths(publication_url)
        if not os.path.exists(selenium_cookies_path) or not self._is_cookie_valid(publication_url) or force:
            self._renew_cookie(publication_url)

        self.api = Api(
            cookies_path=selenium_cookies_path,
            publication_url=publication_url,
        )
        self.api_instances[publication_url] = self.api

    def _is_cookie_valid(self, publication_url: str) -> bool:
        from substack import Api
        from substack.exceptions import SubstackAPIException

        _, selenium_cookies_path = self._get_cookies_paths(publication_url)
        if not os.path.exists(selenium_cookies_path):
            return False
        try:
            temp_api = Api(
                cookies_path=selenium_cookies_path, publication_url=publication_url
            )
            temp_api.get_user_profile()
            return True
        except SubstackAPIException:
            return False

    def _retry_on_error(self, func, max_retries: int = 3, delay: int = 1):
        from substack.exceptions import SubstackAPIException

        for attempt in range(max_retries):
            try:
                return func()
            except SubstackAPIException as e:
                if attempt < max_retries - 1:
                    time.sleep(delay * (2**attempt))
                    pub_url = self.publication_urls[0]
                    self._renew_cookie(pub_url)
                    self._initialize_api(pub_url)
                    continue
                raise

    # ------------------------------------------------------------------
    # Post
    # ------------------------------------------------------------------
    def post(self, text: str, media: list[str] | None = None) -> dict:
        from substack.post import Post

        pub_url = self.publication_urls[0] if self.publication_urls else None
        self._initialize_api(pub_url)

        profile = self._retry_on_error(lambda: self.api.get_user_profile())
        user_id = profile.get("id")
        if not user_id:
            raise ValueError("Could not get user ID from profile")

        post_obj = Post(title="Post", subtitle="", user_id=user_id)

        # Parse simple markdown / text into Substack blocks
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("## "):
                post_obj.add({"type": "heading", "level": 2, "content": line[3:]})
            elif line.startswith("# "):
                post_obj.add({"type": "heading", "content": line[2:]})
            elif line.startswith("!["):
                match = re.match(r"!\[(.*?)\]\((.*?)\)", line)
                if match:
                    alt, src = match.groups()
                    post_obj.add({"type": "captionedImage", "src": src, "caption": alt})
            else:
                post_obj.add({"type": "paragraph", "content": line})

        # Attach local image if provided (media paths from CLI)
        if media:
            if len(media) > 1:
                warnings.warn(
                    "Substack currently supports only one image per post. "
                    "Using the first image only."
                )
            image_path = media[0]
            if os.path.exists(image_path):
                image = self._retry_on_error(lambda: self.api.get_image(image_path))
                post_obj.add({"type": "captionedImage", "src": image.get("url")})

        draft = self._retry_on_error(lambda: self.api.post_draft(post_obj.get_draft()))
        draft_id = draft.get("id")
        if not draft_id:
            raise ValueError("Failed to create draft — no ID returned")

        self._retry_on_error(lambda: self.api.prepublish_draft(draft_id))
        published = self._retry_on_error(lambda: self.api.publish_draft(draft_id))

        return {
            "id": draft_id,
            "title": "Post",
            "status": "published",
            "url": published.get("url", ""),
        }

    # ------------------------------------------------------------------
    # Search — not available
    # ------------------------------------------------------------------
    def search(self, query: str, max_results: int = 10, language: str = "en") -> list[dict]:
        raise NotImplementedError(
            "Substack does not expose a search API. "
            "Use 'social search --backend=twitter' or another backend that supports search."
        )
