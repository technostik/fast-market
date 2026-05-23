# ADR 010: Modal Remote Processing for YouTube Media Pipeline

## Status
Accepted

## Context

The `youtube-cli` publish pipeline (`webux/publish/pipeline.py`) runs three CPU/GPU-intensive steps locally before uploading to YouTube:

1. **Remove silence** — `moviepy` RMS analysis + video concatenation
2. **Transcribe** — `faster-whisper` ASS karaoke subtitle generation
3. **Burn subtitles** — `ffmpeg` subtitle filter

These steps are slow on local hardware, especially transcription (whisper on CPU). Modal (modal.com) is a serverless cloud compute platform that can run Python functions remotely in pre-built containers, with GPU access on the free tier.

**Constraint**: all three steps work with local video files (paths on disk), so files must be serialized as bytes, sent to Modal, and the results written back — they cannot be passed as paths.

**File sizes**: source videos are short YouTube Shorts (<100 MB, typically ~1–10 MB). Byte transfer is acceptable.

## Decision

### Package layout

A `modal_client/` package lives inside `youtube-cli/` alongside `commands/` and `webux/`. It is intentionally named `modal_client/` (not `modal/`) to avoid shadowing the installed `modal` Python package in `sys.path`.

**Planned migration**: this package will eventually move to `common/modal_client/` to be shared across CLIs. No other code needs to change when that happens because it is imported by path (`from modal_client.app import ...`).

```
youtube-cli/
  modal_client/
    __init__.py
    app.py           # modal.App("fast-market") + base_image definition
    diagnose.py      # run_diagnose(), run_file_roundtrip() — used by modal-diagnose command
    remote_steps.py  # run_media_pipeline() — used by the publish pipeline
```

### Single container function

All three media steps are combined into **one** Modal function `run_media_pipeline` in `modal_client/remote_steps.py`. This means:
- One cold start per pipeline run (not three)
- One `app.run()` context manager (not nested)
- All intermediate files stay on the remote machine's `/tmp`

The function is self-contained: the logic from `commands/remove_silence/register.py`, `commands/extract_transcript/register.py`, and `commands/burn_subtitles/register.py` is **duplicated inline** as module-level helper functions (`_remove_silence`, `_detect_silence_segments`, `_transcribe_to_ass`, `_burn_subtitles`, `_ass_to_plain_text`). This is intentional — Modal serializes the function via cloudpickle and the helpers must be importable on the remote worker without mounting local source.

### Function signature

```python
run_media_pipeline(
    video_bytes: bytes,        # input video as bytes
    video_name: str,           # original filename (used for temp paths)
    do_remove_silence: bool,
    threshold: float,          # silence threshold in dB, default -65.0
    do_transcribe: bool,
    ass_bytes: bytes | None,   # pre-existing ASS, used when do_transcribe=False (resume case)
    do_burn_subtitles: bool,
    language: str,             # whisper language code or "auto"
    model_size: str,           # whisper model: tiny/base/small/medium/large
    subtitle_size: int,        # ASS font size
) -> dict:
    # returns:
    # video_bytes      — final output video as bytes
    # video_name       — filename of output video
    # ass_bytes        — ASS subtitle file bytes (empty b"" if not produced)
    # ass_txt          — plain-text transcript (for LLM steps downstream)
    # original_duration — float seconds before silence removal, or None
    # final_duration   — float seconds after silence removal, or None
```

### Pipeline branching

`_run_pipeline_from(job, from_step)` in `pipeline.py` branches at the top of steps 0-2:

```python
if job.use_modal and from_step <= 2:
    current_video, ass_path, txt_path = await _run_modal_steps(job, from_step, ...)
    if job.status == "error":
        return
    await _run_llm_and_upload(job, txt_path, current_video, max(from_step, 3))
    return
# else: existing local path unchanged below
```

Steps 3-5 (LLM title/description generation, YouTube upload, post-publish script) always run locally — they are fast, involve no heavy compute, and require local credentials/network state.

### `_run_modal_steps` async helper

Lives in `pipeline.py`. Handles the file I/O boundary:

1. Reads `current_video` as bytes
2. Resolves `do_remove_silence`, `do_transcribe`, `ass_bytes` from `job` state and `from_step`
3. Marks steps 0-2 as `"running"` in the job object
4. Calls `run_media_pipeline.remote(...)` via `asyncio.to_thread` (blocking call, non-blocking to the event loop) inside `with app.run():`
5. On error: marks affected steps as `"error"`, sets `job.status = "error"`, saves meta, returns
6. On success: writes output video and ASS file to the video source directory (`d`), writes plain-text transcript, updates `job.steps[i].status`, `job.files`, saves meta

`app.run()` is a synchronous context manager — it is safe to use inside an `async` function. The `.remote()` call inside `asyncio.to_thread` prevents blocking the FastAPI event loop.

### Resume compatibility

The `from_step` parameter is respected:

| `from_step` | `do_remove_silence` | `do_transcribe` | `ass_bytes` |
|-------------|---------------------|-----------------|-------------|
| 0 | `job.do_remove_silence` | True | None |
| 1 | False | True | None |
| 2 | False | False | read from `job.files["transcript"]` |

For `from_step == 2`, the existing local `.ass` file is read and passed as `ass_bytes` to Modal so subtitle burning uses the already-computed transcript.

### Job model

`Job` in `models.py` gains `use_modal: bool = True`. It flows through:
- `StartRequest` → `POST /start` → `Job`
- `ResumeRequest` → `POST /resume` → `Job`
- `_create_publish_job()` (pool worker) — uses the `True` default

### UI

A checkbox `id="useModal"` (checked by default) is added to `frontend.html` next to the existing pipeline options. A small `usage ↗` link points to the Modal usage dashboard URL, which is configurable via the config panel (`modal_usage_url` key in publish config, default `https://modal.com/settings`).

### Diagnostic command

`youtube modal-diagnose [--full] [--clip PATH]` tests Modal connectivity. `--full` runs three steps:
1. Environment check (Python version, ffmpeg, whisper, moviepy)
2. File roundtrip: upload clip → ffmpeg remux MKV→MP4 → download
3. Full pipeline: `run_media_pipeline` with `model_size="tiny"` for speed, saves output video and ASS, prints transcript preview

The fixture clip used by default: `tests/fixtures/publish/test_clip.mkv` (6s, ~671 KB).

## Rationale

**Why one function instead of three?** Three separate `@app.function` calls would each need their own `app.run()` context (or the app would need to be deployed). One function has one cold start and keeps intermediate files local to the worker's `/tmp`.

**Why duplicate logic instead of mounting code?** Mounting local source via `modal.Mount` would couple Modal deployment to the local directory layout and slow down iteration. The duplicated helpers are stable (they are exact ports of the command implementations) and easy to audit by diffing with the originals.

**Why `asyncio.to_thread`?** `run_media_pipeline.remote()` is a blocking call. Wrapping it in `asyncio.to_thread` keeps the FastAPI event loop free to serve status polling requests from the frontend while the Modal job is running. Without this, the browser UI would freeze during processing.

**Why does `use_modal` default to `True`?** The free tier ($30/month) is extremely generous for CPU workloads — a 2-minute pipeline at Modal's CPU pricing costs roughly $0.002. Defaulting to remote processing reduces local machine load with effectively zero cost.

## Consequences

- Steps 0-2 produce no granular progress updates when running on Modal (the whole block shows `"running"` until Modal returns). The existing progress bar for local runs is unaffected.
- The output video filename after Modal processing matches what `run_media_pipeline` returns (`video_name` in the result dict), which may differ from the local naming convention (`_subtitled.mp4`). Downstream steps (LLM, upload) use `job.files["final_video"]` which is set correctly regardless.
- Cold starts add ~10-30s overhead on first invocation after a period of inactivity. Subsequent runs within the same session reuse warm containers.
- The `modal_client/` package must be kept in sync with the logic in `commands/remove_silence/`, `commands/extract_transcript/`, and `commands/burn_subtitles/` if those commands are updated. There is no automated check for this drift.
