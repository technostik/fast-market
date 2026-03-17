from __future__ import annotations

import json
from typing import Any


def _as_text(data: Any) -> str:
    if hasattr(data, "read"):
        return data.read()
    return str(data)


def safe_load(text: Any):
    raw = _as_text(text)
    data = {}
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        line = lines[i]
        if ':' not in line:
            i += 1
            continue
        key, val = line.split(':', 1)
        key = key.strip()
        val = val.strip()
        if not val:
            items = []
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith('- '):
                items.append(lines[i].split('- ', 1)[1].strip())
                i += 1
            data[key] = items
            continue
        data[key] = val
        i += 1
    return data


def load(stream: Any, Loader: Any = None):  # noqa: N803
    return safe_load(stream)


def full_load(stream: Any):
    return safe_load(stream)


def safe_dump(obj, stream=None, **kwargs) -> str:
    dumped = json.dumps(obj, indent=2, ensure_ascii=False)
    if stream is None:
        return dumped
    stream.write(dumped)
    return dumped


def dump(obj, stream=None, **kwargs) -> str:
    return safe_dump(obj, stream=stream, **kwargs)


def safe_load_all(stream: Any):
    yield safe_load(stream)


def dump_all(documents, stream=None, **kwargs):
    dumped = "\n---\n".join(safe_dump(doc, **kwargs) for doc in documents)
    if stream is None:
        return dumped
    stream.write(dumped)
    return dumped
