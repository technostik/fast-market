from __future__ import annotations

import json


def safe_load(text: str):
    data = {}
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
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


def safe_dump(obj) -> str:
    return json.dumps(obj, indent=2)
