# How to Build a WebUX Plugin

This document explains how to add a new tab to the `webux serve` interface.

## Architecture Overview

`webux serve` is a FastAPI server that discovers UI tabs dynamically from any `*-cli` package in the monorepo. Each tab is a **webux plugin**: a self-contained module with a frontend HTML page and an optional FastAPI router for its API.

```
your-cli/
└── webux/
    ├── __init__.py
    └── your_plugin/
        ├── __init__.py
        └── register.py          # everything: router, HTML, register()
```

Discovery uses two mechanisms (in order):
1. **Entry points** (`fast_market.webux_plugins` group) — used when packages are installed
2. **Repo layout scan** (`*-cli/webux/*/register.py`) — automatic fallback in dev

---

## Step-by-step

### 1. Create the plugin directory

```
your-cli/webux/__init__.py          # empty
your-cli/webux/your_plugin/__init__.py  # empty
your-cli/webux/your_plugin/register.py
```

### 2. Write `register.py`

Everything lives in one file: the FastAPI router, the HTML, and the `register()` function.

```python
from __future__ import annotations
from fastapi import APIRouter
from common.webux.base import WebuxPluginManifest

router = APIRouter()

@router.get("/hello")
def hello():
    return {"msg": "world"}

_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    body { background:#1a1a2e; color:#eee; font-family:system-ui,sans-serif; padding:16px; }
  </style>
</head>
<body>
  <h2>My Plugin</h2>
  <button onclick="fetch('/api/your_plugin/hello').then(r=>r.json()).then(d=>alert(d.msg))">
    Say hello
  </button>
</body>
</html>"""


def register(config: dict) -> WebuxPluginManifest:
    del config
    return WebuxPluginManifest(
        name="your_plugin",          # unique — used in /api/{name}/* routing
        tab_label="My Plugin",       # text shown in nav bar
        tab_icon="🔧",               # emoji prefix in nav bar
        api_router=router,           # None if no backend API needed
        frontend_html=_HTML,
        order=50,                    # lower = further left in nav
        lazy=True,                   # defer router mount until first request
    )
```

**API routes** are automatically mounted at `/api/{name}/*`, so `@router.get("/hello")` becomes `GET /api/your_plugin/hello`.

### 3. Register in your CLI's `pyproject.toml`

Add the entry point **and** list the webux packages:

```toml
[project.entry-points."fast_market.webux_plugins"]
your_plugin = "webux.your_plugin.register:register"

[tool.setuptools]
packages = [
  # ... existing packages ...
  "webux",
  "webux.your_plugin",
]
```

### 4. Reinstall the CLI

```bash
pip install -e your-cli/
# or
tools/install-all-cli.sh
```

---

## Existing plugins

| Plugin | Location | Tab |
|---|---|---|
| `fileviewer` | `webux-cli/webux/fileviewer/` | Files |
| `yt_poster` | `webux-cli/webux/yt_poster/` | YT Poster |
| `skill_runner` | `webux-cli/webux/skill_runner/` | Skills |
| `corpus` | `corpus-cli/webux/corpus/` | Corpus |
| `corpus_browser` | `corpus-cli/webux/corpus_browser/` | Corpus Browser |
| `publish` | `youtube-cli/webux/publish/` | Publish |

---

## Notes

- **`name` must be unique** across all plugins — webux fails loudly on duplicates.
- **Lazy loading** (`lazy=True`) defers the router mount to the first request. Keep it on unless you need startup-time initialization.
- **`config`** passed to `register(config)` is the merged common config dict — use it to read `workdir`, API keys, etc.
- **Imports inside route handlers** should be lazy (inside the function body) if they depend on packages that may not be on `sys.path` at startup.
- **Frontend**: the HTML is injected after the shared nav bar CSS/JS — no need to replicate the nav.
