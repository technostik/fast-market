# video-agent

## Purpose

Provide the `video` command-line interface for local and Modal-based video preparation used by publishing workflows.

## Architecture Overview

```text
video_entry/__init__.py
        |
        v
cli/main.py
  |       |
  |       +--> common.cli.base (shared Click group and global flags)
  |       +--> common.core.registry (command discovery)
  v
commands/<command>/register.py
  |
  +--> local implementation: ffmpeg, MoviePy, faster-whisper, Pillow
  |
  +--> commands/remote.py
          |
          v
      modal_client/app.py
          |
          +--> remote_steps.py (worker-side media functions)
          +--> diagnose.py (remote environment and transfer checks)
```

`video_entry` exposes `cli.main:main`. `cli/main.py` loads commands from `commands/*/register.py`, attempts to load the repository `.env`, and changes the process working directory to the repository root before importing Modal helpers. `common/` is a symlink to the shared fast-market package.

## Essential Components

| Path | Responsibility |
|------|----------------|
| `video_entry/__init__.py` | Package entry point for the `video` executable |
| `cli/main.py` | Creates the `video-agent` Click group, loads `.env`, and registers discovered commands |
| `commands/base.py` | Defines `CommandManifest`, the contract returned by every command registration |
| `commands/remove_silence/` | RMS silence detection and MoviePy re-encoding |
| `commands/extract_transcript/` | Local or Groq transcription to ASS, SRT, or TXT |
| `commands/burn_subtitles/` | ffmpeg ASS subtitle burn-in |
| `commands/cut/` | Timestamp parsing and stream-copy trimming |
| `commands/concat/` | MoviePy concatenation with H.264/AAC output |
| `commands/duration/` | `ffprobe` duration reporting |
| `commands/assemble/` | Still-image and audio Ken Burns rendering |
| `commands/pipeline/` | Combined silence removal, ASS transcription, and subtitle burn-in |
| `commands/modal_diagnose/` | Modal connectivity, environment, transfer, and full-pipeline checks |
| `commands/remote.py` | Local subprocess-facing bridge to the granular Modal functions |
| `modal_client/app.py` | Modal app, image definition, model preloading, and cancellable call helper |
| `modal_client/remote_steps.py` | Worker-side implementations of media operations |
| `modal_client/diagnose.py` | Remote environment inspection and file round-trip functions |
| `tests/` | Cut, duration, transcription, silence, and subtitle regression tests |

## Core Responsibilities

- Discover and attach every command that exposes a `register(plugin_manifests)` function returning `CommandManifest`.
- Provide the local media operations used directly by people and by `webux-cli` subprocess pipelines.
- Preserve a scripting boundary: status and progress go to stderr; final paths, numeric results, and JSON results go to stdout.
- Route supported operations to Modal without changing their input/output file contract.
- Keep combined-pipeline execution separate from granular execution so publishing jobs can retry or resume stages independently.
- Use the same command names and option contracts in local and remote modes.

## Command Contracts

| Command | Local implementation | Remote implementation |
|---------|----------------------|-----------------------|
| `remove-silence` | `commands/remove_silence/register.py` | `remote_remove_silence` |
| `extract-transcript` | `commands/extract_transcript/register.py` | `remote_extract_transcript` |
| `burn-subtitles` | `commands/burn_subtitles/register.py` | `remote_burn_subtitles` |
| `concat` | `commands/concat/register.py` | `remote_concat_videos` |
| `pipeline` | `commands/pipeline/register.py` | `run_media_pipeline` |
| `cut` | `commands/cut/register.py` | none |
| `duration` | `commands/duration/register.py` | none |
| `assemble` | `commands/assemble/assembler.py` | none |
| `modal-diagnose` | `commands/modal_diagnose/register.py` | `run_diagnose`, `run_file_roundtrip`, and `run_media_pipeline` |

`video pipeline` always generates ASS subtitles and does not expose the granular transcription command's `--use-groq` flag. Publishing integrations should invoke the granular commands when they need independent retry or resume boundaries.

## Dependencies and Integration

### External and system dependencies

- `click` and the shared `common` package provide the CLI and command-discovery integration.
- `auto-click-auto` is currently declared in `pyproject.toml` but is not imported by this package.
- `numpy` provides RMS analysis and image-array operations.
- `moviepy` provides local silence removal, concatenation, and assembly.
- `faster-whisper` provides local transcription.
- `requests` supports the Groq transcription request.
- `modal` provides remote execution and the Modal image.
- `Pillow` is imported by `commands/assemble/assembler.py` but is not currently declared directly in `pyproject.toml`; keep this packaging mismatch visible when changing dependencies.
- `python-dotenv` is an optional import used for repository `.env` loading but is not currently declared directly in `pyproject.toml`.
- `ffmpeg` and `ffprobe` must be installed on the host for local operations.
- The Modal image installs ffmpeg and media Python packages separately in `modal_client/app.py`.

### Repository integrations

- Imports shared CLI and registry code through `common/cli/base.py` and `common/core/registry.py`.
- Is invoked as a subprocess by `webux-cli/webux/short_publish/pipeline.py`, `webux-cli/webux/long_publish/pipeline.py`, and `webux-cli/webux/storyboard/pipeline.py`.
- `webux-cli/webux/short_publish/utils.py` uses `video duration` for progress calculations.
- The design and resume boundaries are recorded in `_doc/adr/010-modal-remote-processing.md`.

## Do's

- Return a `CommandManifest` from every `commands/*/register.py` module.
- Keep command implementations in the command package and shared cross-command behavior in `commands/remote.py` or `modal_client/`.
- Preserve stdout and stderr contracts when adding status output or new commands.
- Validate input paths, timestamps, output requirements, and remote credentials at the command boundary.
- Test both the local and Modal paths when changing a remote-capable operation.
- Use `spawn_and_get` for granular remote calls so SIGINT and SIGTERM can cancel an active Modal function.
- Update `README.md` and this file in the same change as any user-facing command or architecture change.

## Don'ts

- Do not rename `modal_client` to `modal`; the current name avoids shadowing the installed `modal` package.
- Do not mount or import repository code implicitly from a Modal worker; worker helpers must remain serializable and self-contained.
- Do not change one side of a local/remote media algorithm without reviewing and updating the corresponding worker helper.
- Do not use `video pipeline` in a caller that needs independent stage retry or resume behavior.
- Do not describe `cut` as frame-accurate; it uses ffmpeg stream copy.
- Do not claim that the shared `--verbose` flag changes video logging; `cli/main.py` currently configures logging at `CRITICAL`.
- Do not claim that `assemble --zoom-from` or `--zoom-to` overrides a supported motion profile; supported profiles currently define their own motion values.
- Do not swallow media, subprocess, credential, or serialization errors without converting them into an actionable CLI error.
- Do not assume an explicit output parent directory exists.

## Pitfalls

- **Modal package shadowing:** `modal_client` is deliberately distinct from the third-party `modal` package. A rename can make imports resolve to the wrong module.
- **Remote drift:** `modal_client/remote_steps.py` duplicates local silence removal, transcription, subtitle burn-in, and concatenation logic. There is no automated parity check, so review both implementations for every behavior change.
- **Root `.env` and path timing:** `cli/main.py` loads the repository `.env` and changes the working directory to the repository root before Modal imports and Click parses arguments. Modal's `Secret.from_dotenv()` also depends on that root file; running from another directory without this setup can produce an empty remote secret, and relative file arguments are resolved from the repository root.
- **Packaging omissions:** `pyproject.toml` uses an explicit package list that currently omits newer command packages and `common`. The documented editable checkout install can work while a clean wheel install is incomplete; do not assume packaging parity without a build-and-install check.
- **Missing output parents:** Most commands write directly to the resolved output path and do not create its parent directory.
- **Silence failure modes:** A file with no usable audio raises `SilentVideoError`. The local implementation removes and rejects a result that is not shorter than the source; the current Modal worker returns the resulting video without that additional check.
- **Stream-copy cuts:** `cut` avoids re-encoding, so keyframes and timestamps can make an arbitrary cut point imprecise.
- **Assembly zoom options:** Supported named and dynamic motion profiles currently ignore the CLI zoom fallback values.
- **Model availability:** The Modal image preloads the `medium` Whisper model. Other requested model sizes may need runtime download or may fail in a restricted worker environment.
- **Pipeline feature asymmetry:** `extract-transcript --use-groq` is not a `video pipeline` option; do not infer that the combined command accepts every granular option.
- **Modal transcript format asymmetry:** Modal Groq transcription is used for ASS output only; SRT and TXT requests use the worker's `faster-whisper` path.

## Tests

Run the package tests from the repository root:

```bash
pytest video-cli/tests/ -v
```

Or run them from `video-cli/`:

```bash
cd video-cli
pytest tests/
```

The suite covers:

- Timestamp parsing, `head`/`tail` selection, and stream-copy failure handling in `tests/test_cut.py`.
- `ffprobe` duration success and failure handling in `tests/test_duration.py`.
- ASS generation, silence removal, and subtitle-burn regressions in `tests/test_publish_regression.py`.

The publish tests require the direct media dependencies (`moviepy` and `faster-whisper`) and fail with `ModuleNotFoundError` when those packages are unavailable; they are not conditionally skipped for missing packages. Golden fixtures can be regenerated with `pytest video-cli/tests/test_publish_regression.py --generate-golden`; regeneration overwrites fixtures and may invoke a real model, so use it only for intentional behavior changes.

## Observability

- Command status messages use `click.echo(..., err=True)` and are intended for stderr.
- Final output paths are printed to stdout by file-producing commands.
- `video duration` prints only the three-decimal numeric result.
- `video assemble --format json` prints one JSON object for scripting.
- `video modal-diagnose` reports the remote Python, ffmpeg, faster-whisper, and MoviePy environment.
- `video modal-diagnose --full` additionally verifies an ffmpeg byte round trip and a tiny-model media pipeline; it creates local temporary output files and uses remote resources.
- The root `--verbose/-v` option is inherited from `common.cli.base`, but video currently configures logging at `CRITICAL`; use the explicit status messages and diagnostic command for troubleshooting.

## Extension Points

### Add a local command

1. Create `commands/your_command/` with `__init__.py` and `register.py`.
2. Define a Click command whose arguments and options represent the file-level contract.
3. Return `CommandManifest(name=..., click_command=...)` from `register(plugin_manifests)`.
4. Add local tests for successful and failure paths, then update `README.md` and this file.

`common.core.registry.discover_commands` finds the new registration automatically.

### Add a remote-capable operation

1. Implement the worker-side function in `modal_client/remote_steps.py` with byte-oriented inputs and outputs.
2. Add the local bridge in `commands/remote.py` and the `--modal/--local` option to the command.
3. Preserve the same output path, format, error, and stdout/stderr contract as local mode.
4. Test serialization, remote failure handling, and local/remote parity.
5. Update ADR 010 when a transport, cancellation, or resume boundary changes.

### Add a new motion profile

1. Add its normalized zoom and anchor tuple to `_PROFILES` or the appropriate dynamic-motion list in `commands/assemble/assembler.py`.
2. Keep the profile name in the Click choices generated from `MOTION_CHOICES`.
3. Verify the output remains 1280×720 and that the profile does not require changes to the documented zoom fallback behavior.

## Related Documentation

- See [`README.md`](README.md) for installation, configuration, examples, and the CLI reference.
- See [`../_doc/adr/010-modal-remote-processing.md`](../_doc/adr/010-modal-remote-processing.md) for Modal transport, cancellation, and resume decisions.
- See [`../common/core/registry.py`](../common/core/registry.py) for command discovery.
- See [`../common/cli/base.py`](../common/cli/base.py) for shared global options.
- See [`../.doc/GOLDEN_RULES.md`](../.doc/GOLDEN_RULES.md) for repository documentation and change rules.
