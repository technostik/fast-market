from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException


def _assert_path_safe(path: Path, roots: list[Path]) -> None:
    candidate = path.expanduser().resolve()
    resolved_roots = [root.expanduser().resolve() for root in roots if root]
    for root in resolved_roots:
        try:
            candidate.relative_to(root)
            return
        except ValueError:
            continue
    raise HTTPException(status_code=403, detail="Path is outside allowed roots")
