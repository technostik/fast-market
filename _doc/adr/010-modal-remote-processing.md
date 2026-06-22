# ADR 010: Modal Remote Processing for Video Media Pipeline

## Status
Accepted

## Context

The `webux-cli` short publish pipeline (`webux/short_publish/pipeline.py`) delegates three CPU/GPU-intensive steps to the standalone `video` CLI before uploading to YouTube:

1. **Remove silence** — `moviepy` RMS analysis + video concatenation
2. **Transcribe** — `faster-whisper` ASS karaoke subtitle generation
3. **Burn subtitles** — `ffmpeg` subtitle filter

These steps are slow on local hardware, especially transcription (whisper on CPU). Modal (modal.com) is a serverless cloud compute platform that can run Python functions remotely in pre-built containers, with GPU access on the free tier.

**Constraint**: all three steps work with local video files (paths on disk), so files must be serialized as bytes, sent to Modal, and the results written back — they cannot be passed as paths.

**File sizes**: source videos are short YouTube Shorts (<100 MB, typically ~1–10 MB). Byte transfer is acceptable.

## Decision

### Package layout

A `modal_client/` package lives inside `video-cli/` alongside the media-processing `commands/`. It is intentionally named `modal_client/` (not `modal/`) to avoid shadowing the installed `modal` Python package in `sys.path`.

```
video-cli/
  modal_client/
    __init__.py
    app.py           # modal.App("fast-market") + base_image definition
    diagnose.py      # run_diagnose(), run_file_roundtrip() — used by modal-diagnose command
    remote_steps.py  # per-step remote functions plus run_media_pipeline() for combined runs
```

### Single container function

The media steps can run as **one** Modal function (`run_media_pipeline`) for combined video pipeline runs, or as granular per-step functions (`remote_remove_silence`, `remote_extract_transcript`, `remote_burn_subtitles`) for resumable publish jobs. This means:
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

`_run_pipeline_from(job, from_step)` in `webux-cli/webux/short_publish/pipeline.py` preserves per-step resume semantics by invoking `video remove-silence`, `video extract-transcript`, and `video burn-subtitles` as subprocesses. When `job.use_modal` is true, each subprocess receives `--modal`; otherwise it uses the default local path. The webux pipeline intentionally does **not** call `video pipeline`, because that combined command would collapse independent step retry/resume behavior.

Steps 3-5 (LLM title/description generation, YouTube upload, post-publish script) always run locally — they are fast, involve no heavy compute, and require local credentials/network state.

### Per-step subprocess boundary

`webux-cli/webux/short_publish/utils.py` resolves the `video` binary with `_video()`, matching the existing `_yt()` and `_pr()` helpers. The publish pipeline captures stdout/stderr through the shared `_run()` subprocess helper so status output remains visible in the web UI.

### Resume compatibility

The `from_step` parameter is respected:

| `from_step` | `do_remove_silence` | `do_transcribe` | `ass_bytes` |
|-------------|---------------------|-----------------|-------------|
| 0 | `video remove-silence` | source video | `job.files["no_silence"]` |
| 1 | `video extract-transcript` | no-silence video or source | `job.files["transcript"]` and transcript text |
| 2 | `video burn-subtitles` | current video + existing ASS | `job.files["subtitled"]` |

For `from_step == 2`, the existing local `.ass` file path is passed to `video burn-subtitles` so subtitle burning uses the already-computed transcript.

### Job model

`Job` in `models.py` gains `use_modal: bool = True`. It flows through:
- `StartRequest` → `POST /start` → `Job`
- `ResumeRequest` → `POST /resume` → `Job`
- `_create_publish_job()` (pool worker) — uses the `True` default

### UI

A checkbox `id="useModal"` (checked by default) is added to `frontend.html` next to the existing pipeline options. A small `usage ↗` link points to the Modal usage dashboard URL, which is configurable via the config panel (`modal_usage_url` key in publish config, default `https://modal.com/settings`).

### Diagnostic command

`video modal-diagnose [--full] [--clip PATH]` tests Modal connectivity. `--full` runs three steps:
1. Environment check (Python version, ffmpeg, whisper, moviepy)
2. File roundtrip: upload clip → ffmpeg remux MKV→MP4 → download
3. Full pipeline: `run_media_pipeline` with `model_size="tiny"` for speed, saves output video and ASS, prints transcript preview

The fixture clip used by default: `video-cli/tests/fixtures/publish/test_clip.mkv` (6s, ~671 KB).

## Rationale

**Why one function instead of three?** Three separate `@app.function` calls would each need their own `app.run()` context (or the app would need to be deployed). The combined `video pipeline --modal` path has one cold start and keeps intermediate files local to the worker's `/tmp`; resumable webux jobs use per-step calls to preserve retry boundaries.

**Why duplicate logic instead of mounting code?** Mounting local source via `modal.Mount` would couple Modal deployment to the local directory layout and slow down iteration. The duplicated helpers are stable (they are exact ports of the command implementations) and easy to audit by diffing with the originals.

**Why `asyncio.to_thread`?** `run_media_pipeline.remote()` is a blocking call. Wrapping it in `asyncio.to_thread` keeps the FastAPI event loop free to serve status polling requests from the frontend while the Modal job is running. Without this, the browser UI would freeze during processing.

**Why does `use_modal` default to `True`?** The free tier ($30/month) is extremely generous for CPU workloads — a 2-minute pipeline at Modal's CPU pricing costs roughly $0.002. Defaulting to remote processing reduces local machine load with effectively zero cost.

## Consequences

- Steps 0-2 produce no granular progress updates when running on Modal (the whole block shows `"running"` until Modal returns). The existing progress bar for local runs is unaffected.
- Cold starts add ~10-30s overhead on first invocation after a period of inactivity. Subsequent runs within the same session reuse warm containers.
- The `video-cli/modal_client/` package must be kept in sync with the logic in `video-cli/commands/remove_silence/`, `video-cli/commands/extract_transcript/`, and `video-cli/commands/burn_subtitles/` if those commands are updated. There is no automated check for this drift.
