"""LinkedIn backend plugin."""

from __future__ import annotations

import json
import os
import re
import warnings
from typing import Any

import requests

from plugins.base import SocialPlugin


class LinkedinPlugin(SocialPlugin):
    """Plugin for posting to and searching on LinkedIn."""

    name = "linkedin"

    def __init__(self, config: dict):
        self._config = config
        self.client_id = config.get("linkedin_client_id", "")
        self.client_secret = config.get("linkedin_client_secret", "")
        self.base_url = "https://api.linkedin.com"
        self.access_token = config.get("linkedin_access_token", "")
        self.redirect_uri = config.get("linkedin_redirect_uri", "https://your-app.com/callback")
        self.api_version = config.get("linkedin_api_version", "202504")
        self.person_urn: str | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_person_urn(self) -> str | None:
        if self.person_urn:
            return self.person_urn
        try:
            headers = self._auth_headers()
            resp = requests.get(f"{self.base_url}/v2/userinfo", headers=headers)
            resp.raise_for_status()
            user_data = resp.json()
            self.person_urn = f"urn:li:person:{user_data['sub']}"
            return self.person_urn
        except Exception as e:
            raise RuntimeError(f"Failed to get LinkedIn person URN: {e}") from e

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": self.api_version,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _escape_text(text: str) -> str:
        """Escape characters that LinkedIn API has issues with."""
        if not text:
            return text
        for char in ["(", ")", "[", "]", "{", "}", "@", "_", "~"]:
            text = text.replace(char, f"\\{char}")
        return text

    # ------------------------------------------------------------------
    # Post
    # ------------------------------------------------------------------
    def post(self, text: str, media: list[str] | None = None) -> dict:
        person_urn = self._ensure_person_urn()
        if not person_urn:
            raise RuntimeError("Could not resolve LinkedIn person URN.")

        headers = self._auth_headers()
        latest_version = "202507"
        headers["LinkedIn-Version"] = latest_version

        image_urn = None
        if media:
            if len(media) > 1:
                warnings.warn(
                    "LinkedIn API currently supports only one image per post. "
                    "Using the first image only."
                )
            image_urn = self._upload_image(media[0], person_urn, latest_version)

        # Prepare text
        full_text = self._escape_text(text)
        if len(full_text) > 3000:
            full_text = full_text[:2997] + "..."
            warnings.warn("Content truncated to 3000 characters (LinkedIn limit)")

        body: dict[str, Any] = {
            "author": person_urn,
            "commentary": full_text,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED"},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        if image_urn:
            body["content"] = {
                "media": {
                    "title": "Post",
                    "id": image_urn,
                }
            }

        resp = requests.post(f"{self.base_url}/rest/posts", headers=headers, json=body)
        if resp.status_code not in (201, 200):
            raise RuntimeError(f"LinkedIn post failed ({resp.status_code}): {resp.text}")

        post_id = resp.headers.get("x-restli-id") or resp.json().get("id", "N/A")
        return {
            "id": post_id,
            "status": "success",
            "character_count": len(full_text),
        }

    def _upload_image(self, image_path: str, person_urn: str, version: str) -> str | None:
        if not os.path.exists(image_path):
            warnings.warn(f"Image file not found: {image_path}")
            return None

        ext = os.path.splitext(image_path)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif"):
            warnings.warn(f"Unsupported image format: {ext}. Use PNG, JPEG, or GIF.")
            return None

        init_headers = {
            **self._auth_headers(),
            "LinkedIn-Version": version,
        }
        init_body = {"initializeUploadRequest": {"owner": person_urn}}
        init_url = f"{self.base_url}/rest/images?action=initializeUpload"
        init_resp = requests.post(init_url, headers=init_headers, json=init_body)
        init_resp.raise_for_status()
        init_data = init_resp.json()["value"]
        upload_url = init_data["uploadUrl"]
        image_urn = init_data["image"]

        with open(image_path, "rb") as f:
            upload_resp = requests.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": f"image/{ext.lstrip('.')}",
                },
                data=f,
            )
            upload_resp.raise_for_status()

        return image_urn

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, max_results: int = 10, language: str = "en") -> list[dict]:
        try:
            headers = self._auth_headers()
            params = {
                "q": query,
                "count": max_results,
                "sort": "relevance",
                "locale.language": language,
            }
            resp = requests.get(f"{self.base_url}/v2/search", headers=headers, params=params)
            resp.raise_for_status()
            elements = resp.json().get("elements", [])

            results = []
            for post in elements:
                commentary = post.get("commentary", {})
                text = ""
                if isinstance(commentary, dict):
                    text = commentary.get("text", "")
                results.append(
                    {
                        "id": post.get("id"),
                        "text": text,
                        "author": post.get("author", {}).get("name", "N/A"),
                        "created_at": post.get("lastModifiedTime", {}).get("time", "N/A"),
                        "url": post.get("url", "N/A"),
                    }
                )
            return results
        except Exception as e:
            warnings.warn(f"LinkedIn search error: {e}")
            return []
