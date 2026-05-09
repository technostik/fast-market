from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from plugins.base import ItemMetadata, SourcePlugin


def _get_content_type_from_extension(file_path: Path) -> str:
    """Determine content type based on file extension."""
    ext = file_path.suffix.lower()
    content_types = {
        '.txt': 'document',
        '.md': 'document',
        '.pdf': 'document',
        '.doc': 'document',
        '.docx': 'document',
        '.jpg': 'image',
        '.jpeg': 'image',
        '.png': 'image',
        '.gif': 'image',
        '.bmp': 'image',
        '.svg': 'image',
        '.mp4': 'video',
        '.avi': 'video',
        '.mkv': 'video',
        '.mp3': 'audio',
        '.wav': 'audio',
        '.flac': 'audio',
        '.zip': 'archive',
        '.tar': 'archive',
        '.gz': 'archive',
        '.rar': 'archive',
        '.json': 'data',
        '.xml': 'data',
        '.csv': 'data',
        '.py': 'code',
        '.js': 'code',
        '.html': 'code',
        '.css': 'code',
    }
    return content_types.get(ext, 'file')


class DirectoryPlugin(SourcePlugin):
    name = "directory"

    async def fetch_new_items(
        self,
        last_item_id: str | None = None,
        limit: int = 50,
        last_fetched_at: datetime | None = None,
        force: bool = False,
        seen_item_ids: set[str] | None = None,
    ) -> list[ItemMetadata]:
        if not self._should_fetch(force):
            return []

        directory_path = Path(self.source_config["origin"])

        try:
            # List all files in the directory (non-recursive for now)
            files = [f for f in directory_path.iterdir() if f.is_file()]
        except (OSError, PermissionError) as e:
            # Log error and return empty list
            print(f"Error accessing directory {directory_path}: {e}")
            return []

        # Sort files by modification time (oldest first)
        files.sort(key=lambda f: f.stat().st_mtime)

        items = []
        found_last = last_item_id is None

        for file_path in files:
            if len(items) >= limit:
                break

            file_id = str(file_path.resolve())  # Use absolute path as unique ID

            if not found_last:
                if file_id == last_item_id:
                    found_last = True
                continue  # Skip until we find the last_item_id

            try:
                stat = file_path.stat()
                published_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

                item = ItemMetadata(
                    id=file_id,
                    title=file_path.name,
                    url=str(file_path.resolve()),
                    published_at=published_at,
                    content_type=_get_content_type_from_extension(file_path),
                    source_plugin=self.name,
                    source_id=self.source_config.get("id", ""),
                    extra={
                        "file_size": stat.st_size,
                        "extension": file_path.suffix,
                        "permissions": oct(stat.st_mode)[-3:],  # e.g., '644'
                        "directory": str(directory_path),
                    },
                )
                items.append(item)
            except (OSError, PermissionError) as e:
                print(f"Error accessing file {file_path}: {e}")
                continue

        return items

    def validate_identifier(self, identifier: str) -> bool:
        return os.path.isdir(identifier)

    def get_identifier_display(self, identifier: str) -> str:
        return identifier
