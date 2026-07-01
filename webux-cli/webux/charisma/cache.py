from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

CACHE_FILENAME = ".charisma-scores.json"

# One lock per folder, so concurrent workers analyzing files in the same
# folder don't clobber each other's read-modify-write of the cache file.
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def cache_path(folder: Path) -> Path:
    return folder / CACHE_FILENAME


def load_cache(folder: Path) -> dict[str, Any]:
    p = cache_path(folder)
    if not p.exists():
        return {"version": 1, "files": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data.setdefault("files", {})
        return data
    except Exception:
        return {"version": 1, "files": {}}


def get_cached_entry(cache: dict[str, Any], file: Path) -> dict[str, Any] | None:
    """Return the cached entry for `file` if present and still valid
    (mtime/size unchanged since it was scored), else None."""
    entry = cache.get("files", {}).get(file.name)
    if not entry:
        return None
    try:
        stat = file.stat()
    except OSError:
        return None
    if entry.get("mtime") != stat.st_mtime or entry.get("size") != stat.st_size:
        return None
    return entry


def lock_for(folder: Path) -> asyncio.Lock:
    return _locks[str(folder)]


async def save_cache_entry(folder: Path, file: Path, scores: dict[str, Any]) -> None:
    async with lock_for(folder):
        cache = load_cache(folder)  # re-read under the lock: another worker may have written since
        stat = file.stat()
        cache["files"][file.name] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "analyzed_at": time.time(),
            "scores": scores,
        }
        cache_path(folder).write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
