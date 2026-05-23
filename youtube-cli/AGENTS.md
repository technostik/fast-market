# youtube-cli/

## Purpose
YouTube CLI tool for searching videos, fetching/posting comments, and publishing YouTube Shorts. Includes a full media processing pipeline (silence removal, transcription, subtitle burning) that runs locally or remotely on Modal serverless compute.

## Essential Components

- `youtube_entry/__init__.py` — Entry point exporting `main()`
- `cli/main.py` — Click CLI group; calls `discover_commands()` to load all commands
- `core/engine.py` — Factory for authenticated YouTube API clients
- `core/config.py` — YouTube-specific config loader
- `commands/base.py` — `CommandManifest` dataclass; every command returns one
- `modal_client/app.py` — `modal.App("fast-market")` + `base_image` (ffmpeg + faster-whisper + moviepy)
- `modal_client/remote_steps.py` — `run_media_pipeline()`: all three media steps in one Modal container call
- `webux/publish/pipeline.py` — Async publish pipeline orchestration (local and Modal paths)
- `webux/publish/models.py` — `Job` and `Step` dataclasses; `Job.use_modal` controls routing
- `webux/publish/register.py` — FastAPI router for the publish webux plugin

## Core Responsibilities

- YouTube Data API v3 operations (search, comments, upload)
- Video download and caching via yt-dlp
- Media processing: silence removal (moviepy), transcription (faster-whisper), subtitle burning (ffmpeg)
- Remote media processing via Modal (transparent to callers via `job.use_modal`)
- OAuth 2.0 authentication and quota tracking
- Webux publish plugin: full Shorts production pipeline with queue management

## Command Discovery

`common.core.registry.discover_commands()` scans `commands/` at startup. Any directory with a `register.py` containing `def register(plugin_manifests) -> CommandManifest` is auto-loaded. No manual registration required.

**To add a command:** create `commands/my_command/register.py`, implement `register()`, done.

## Publish Pipeline

Steps 0-2 (media) can run locally or on Modal. Steps 3-5 always run locally.

```
0. Remove silence     (moviepy)         — local or Modal
1. Extract transcript (faster-whisper)  — local or Modal
2. Burn subtitles     (ffmpeg)          — local or Modal
3. Generate title/desc (LLM via prompt-cli) — always local
4. Upload to YouTube   (youtube upload)     — always local
5. Post-publish script (bash)               — always local
```

The branch is in `pipeline._run_pipeline_from()`:

```python
if job.use_modal and from_step <= 2:
    await _run_modal_steps(job, from_step, ...)
    await _run_llm_and_upload(...)
    return
# else: local path unchanged below
```

## Modal Integration

See `_doc/adr/010-modal-remote-processing.md` for the full design.

Key points for agents:
- **Package name**: `modal_client/` not `modal/` — avoids shadowing the installed `modal` package in `sys.path`
- **One function**: `run_media_pipeline()` in `remote_steps.py` runs all three steps in one container (one cold start)
- **Self-contained**: helper functions (`_remove_silence`, `_transcribe_to_ass`, `_burn_subtitles`) are duplicated in `remote_steps.py` — do NOT import from `commands/` inside Modal functions (the worker has no local source)
- **File transfer**: video is passed as `bytes`, results come back as `bytes` and are written to disk by `_run_modal_steps`
- **Async boundary**: `.remote()` is blocking; it is called inside `asyncio.to_thread()` to keep the FastAPI event loop free
- **`app.run()` context**: wraps the single `.remote()` call; it is a sync context manager and is safe inside an `async def`
- **Drift risk**: if `commands/remove_silence/`, `commands/extract_transcript/`, or `commands/burn_subtitles/` logic changes, `remote_steps.py` helpers must be updated manually — there is no automated check

## Do's

- Use `CommandManifest` for every command returned from `register()`
- Use `click.echo(..., err=True)` for progress/status, `click.echo(result)` for pipeable output
- Use `click.ClickException` for user-facing errors
- Use `asyncio.to_thread()` for any blocking call inside the async pipeline
- Keep `modal_client/remote_steps.py` helpers fully self-contained (no local imports from `commands/`)
- Import `modal_client.*` lazily (inside functions) in pipeline code — `modal` startup is slow and should not block the webux server on import

## Don'ts

- Don't name anything `modal/` as a package — it shadows the installed `modal` package
- Don't call `run_media_pipeline.remote()` outside an `app.run()` context (ephemeral run pattern)
- Don't import from `commands/` inside any `@app.function` — the Modal worker has no local source tree
- Don't run steps 3-5 (LLM, upload, post-script) on Modal — they need local credentials and network state
- Don't hardcode file paths; use `pub_cfg.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH)`
- Don't bypass OAuth; always use `YouTubeOAuth` from `common.auth`
- Don't ignore quota tracking; always pass `quota_limit` to `YouTubeClient`

## Key Data Flows

### Local media pipeline (steps 0-2)
```
job.source (path) → remove_silence_simple() → generate_karaoke_ass() → burn_ass_subtitles()
                                                                          ↓
                                                               job.files["subtitled"]
```

### Modal media pipeline (steps 0-2)
```
job.source (path) → read bytes → run_media_pipeline.remote(bytes) → result dict
                                                                       ↓
                                              write video bytes + ass bytes to disk
                                                                       ↓
                                                          job.files["subtitled"] / ["transcript"]
```

### Resume from step 2 (Modal)
```
job.files["transcript"] (.ass path) → read bytes → pass as ass_bytes param
→ run_media_pipeline(do_transcribe=False, ass_bytes=...) → burn only
```

## Testing

```bash
# Unit / regression tests
cd youtube-cli && pytest tests/

# Modal connectivity
youtube modal-diagnose

# Full Modal pipeline test (uses tiny whisper model, ~30s)
youtube modal-diagnose --full

# Custom clip
youtube modal-diagnose --full --clip /path/to/video.mkv
```

## Related Documentation

- `_doc/adr/010-modal-remote-processing.md` — Modal integration design decisions
- `README.md` — Full CLI reference with examples
- `webux/publish/frontend.html` — Publish UI (single-page, no framework)
- [Modal documentation](https://modal.com/docs)
- [YouTube Data API v3](https://developers.google.com/youtube/v3)
