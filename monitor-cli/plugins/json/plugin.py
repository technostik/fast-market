from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any

from plugins.base import SourcePlugin, ItemMetadata


class JsonPlugin(SourcePlugin):
    """Monitor items from a JSON source produced by a custom command.

    Metadata:
        command: Shell command that outputs a JSON array of items.
                 Each item should have: item_id, item_title, item_url,
                 item_content_type, item_published (ISO or unix timestamp).

    The command is executed and its stdout is parsed as JSON.
    Expected output: an array of objects, or a single object wrapped in an array.
    """

    name = "json"

    def __init__(self, config: dict, source_config: dict):
        super().__init__(config, source_config)
        self.source_id = source_config.get("id", "")
        self.command = self.metadata.get("command")
        if not self.command:
            raise ValueError(
                "json plugin requires 'command' in metadata. "
                "The command must output a JSON array of items to stdout."
            )

    def validate_identifier(self, identifier: str) -> bool:
        """For json plugin, origin is a placeholder; validation is on metadata command."""
        return True

    def get_identifier_display(self, identifier: str) -> str:
        cmd_display = self.command[:50] + "..." if len(self.command) > 50 else self.command
        return f"cmd: {cmd_display}"

    def _parse_published(self, value: Any) -> datetime:
        """Parse a published timestamp value into a datetime."""
        if value is None:
            return datetime.now(timezone.utc)

        # If it's a number, treat as unix timestamp
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)

        # Parse as ISO string
        value = str(value).strip()
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)

    def _normalize_content_type(self, ct: str | None) -> str:
        """Normalize content_type to expected values."""
        if not ct:
            return "article"
        ct = ct.lower().strip()
        valid_types = {"video", "short", "article", "medium_video", "long_video"}
        if ct in valid_types:
            return ct
        return "article"

    async def fetch_new_items(
        self,
        last_item_id: str | None = None,
        limit: int = 50,
        last_fetched_at: Any | None = None,
        force: bool = False,
    ) -> list[ItemMetadata]:
        """Execute the command, parse JSON output, return items."""
        if not self._should_fetch(force):
            return []

        try:
            result = subprocess.run(
                self.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                print(f"⚠️ json plugin command exited with code {result.returncode}: {result.stderr[:500]}")
                return []

            stdout = result.stdout.strip()
            if not stdout:
                return []

            data = json.loads(stdout)

            # Normalize to list
            if isinstance(data, dict):
                data = [data]
            elif not isinstance(data, list):
                print(f"⚠️ json plugin: expected JSON array or object, got {type(data).__name__}")
                return []

            items: list[ItemMetadata] = []
            for entry in data[:limit]:
                if not isinstance(entry, dict):
                    continue

                item_id = str(entry.get("item_id", entry.get("id", "")))
                if not item_id:
                    continue

                title = str(entry.get("item_title", entry.get("title", "")))
                url = str(entry.get("item_url", entry.get("url", "")))
                content_type = self._normalize_content_type(
                    entry.get("item_content_type", entry.get("content_type"))
                )
                published_at = self._parse_published(
                    entry.get("item_published", entry.get("published"))
                )

                # Build extra dict from remaining fields
                known_keys = {"item_id", "item_title", "item_url", "item_content_type", "item_published",
                              "id", "title", "url", "content_type", "published"}
                extra = {k: v for k, v in entry.items() if k not in known_keys}
                extra["source_command"] = self.command

                items.append(
                    ItemMetadata(
                        id=item_id,
                        title=title,
                        url=url,
                        published_at=published_at,
                        content_type=content_type,
                        source_plugin=self.name,
                        source_id=self.source_id,
                        extra=extra,
                    )
                )

            # Sort by published date, newest first
            items.sort(key=lambda x: x.published_at, reverse=True)

            return items

        except subprocess.TimeoutExpired:
            print(f"⚠️ json plugin command timed out (60s): {self.command}")
            return []
        except json.JSONDecodeError as e:
            print(f"⚠️ json plugin: invalid JSON output: {e}")
            return []
        except Exception as e:
            print(f"⚠️ json plugin failed: {e}")
            return []

    async def close(self):
        pass
