# common

## 🎯 Purpose
Shared library for all fast-market CLI agents. Contains cross-cutting infrastructure (logging, subprocess, config, LLM, auth, storage) that every tool imports. Deleting a specific CLI tool (`*-cli/`) must leave this module intact and working.

## 🏗️ Architecture

```
common/
├── structlog.py        # Logging shim — get_logger(name) → _Logger
├── rt_subprocess.py    # Real-time subprocess capture — rt_subprocess.run()
├── last_video.py       # get_last_video() — RSS + yt-dlp fallback, short/normal filter
│
├── agent/              # Agentic loop, session model, executor, prompts, shared context
├── auth/               # AuthProvider ABC
├── cli/                # Click group factory + output helpers
├── core/               # Paths (XDG), config loading, registry, duration, aliases, yaml utils
├── llm/                # LLM provider abstraction (Anthropic, OpenAI, Ollama, Groq, xAI…)
├── prompt/             # PromptManager — per-tool prompt overrides
├── storage/            # SQLAlchemy engine/session helpers
├── webux/              # Webux hub plugin contract and discovery
└── youtube/            # YouTube API client, auth, models, transport, quota
```

## 📋 Core Responsibilities
- Provide a single `structlog.get_logger(name)` that all modules use for structured logging
- Provide `rt_subprocess.run()` as a drop-in for `subprocess.run()` that streams output in real time
- Provide `get_last_video()` as a shared utility for fetching the latest video from a YouTube channel

## 🔗 Dependencies & Integration
- Used by: all `*-cli/` packages — they import from `common.*`
- External deps: `click`, `pyyaml`, `sqlalchemy`, `pydantic`, `feedparser`, `yt-dlp`, `google-api-python-client` (not all required by every consumer)

## Root-level Utilities

### `structlog.py`
A thin logging shim over Python's `logging` stdlib. All loggers share a single `StreamHandler` on stderr.

```python
from common import structlog
logger = structlog.get_logger(__name__)
logger.info("event_name", key="value")
```

- Verbosity controlled globally: `logging.root.setLevel(logging.DEBUG)` before any logger is created activates debug output retroactively
- Enable verbose logging without code changes: call `logging.root.setLevel(logging.DEBUG)` early in the CLI entry point (typically triggered by `--verbose`)

### `rt_subprocess.py`
Drop-in for `subprocess.run()` with real-time line-by-line capture. Useful when running long-running subprocesses where you want output streamed immediately instead of buffered.

```python
from common.rt_subprocess import rt_subprocess
result = rt_subprocess.run(["my-tool", "arg"], capture_output=True, text=True)
```

⚠️ The file contains dead code below line 78 (unreachable duplicate block inside `_run_with_real_time`). It has no effect at runtime — the function returns at line 76.

### `last_video.py`
Fetches the most recent video(s) from a YouTube channel. Used by multiple CLIs to obtain the latest video URL for processing.

```python
from common.last_video import get_last_video

video = get_last_video(
    channel_id="UCxxxxxx",
    short=False,   # only normal videos
    normal=True,
    offset=1,      # 1 = most recent
)
# Returns {"id": "...", "title": "...", "url": "...", "published": datetime, "duration": int}
```

Transport chain: RSS feed → yt-dlp fallback. Uses `RSSPlaylistTransport` from `common.youtube.transport`.

## ✅ Do's
- Import `structlog` from `common` (not `structlog` the PyPI package)
- Use `rt_subprocess` only for long-running processes where live output matters
- Use `get_last_video()` when any CLI needs the latest channel video

## ❌ Don'ts
- Do not use `logging` directly in agent code — use `common.structlog`
- Do not import `subprocess` directly when you need real-time streaming — use `rt_subprocess`

## ⚠️ Pitfalls
- `rt_subprocess.py` has unreachable dead code after its first `return` (lines 80–117). This is a known artifact. Do not edit the dead block expecting it to run.
- `last_video.py` and `common/youtube/utils.py` both have an `is_short_video()` function with **different** thresholds (180 s vs 60 s). Always check which module you are importing from.

## 📚 Related Documentation
- See `common/agent/AGENTS.md` for the agentic loop
- See `common/core/AGENTS.md` for path management and config loading
- See `common/llm/AGENTS.md` for LLM provider configuration
- See `common/youtube/AGENTS.md` for YouTube API client details
