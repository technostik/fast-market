# video-agent

`video` is a Click CLI for preparing video assets: remove silence, transcribe speech, burn subtitles, trim or concatenate clips, inspect duration, assemble image-and-audio clips, and run a combined publishing pipeline locally or on Modal.

## Installation

Install the CLI from this repository checkout:

```bash
python -m pip install -e "./video-cli"
```

The command is then available as `video`:

```bash
video --help
```

### Prerequisites

- Python 3.11 or higher
- `ffmpeg` and `ffprobe` available on `PATH` for local media processing
- The Python dependencies declared in `video-cli/pyproject.toml`
- Modal authentication for `--modal` and `modal-diagnose`
- `GROQ_API_KEY` only when using `extract-transcript --use-groq`

Check the system media tools with:

```bash
ffmpeg -version
ffprobe -version
```

Modal authentication is configured with the installed Modal CLI:

```bash
modal setup
video modal-diagnose
```

`modal-diagnose --full` performs a remote media run and can consume Modal resources; use it as an integration check rather than as a default smoke test.

## Configuration

`video-agent` does not have a video-specific YAML configuration file. Command behavior is controlled by CLI options and environment variables.

| Setting | How it is used |
|---------|----------------|
| `GROQ_API_KEY` | Required for local `extract-transcript --use-groq`; required on Modal for ASS output |
| `FASTMARKET_PROFILE` | Selects the shared fast-market profile; the global `--profile/-P` flag overrides it |
| Modal credentials | Managed by the Modal CLI through `modal setup` |

At startup, the CLI attempts to load `.env` from the repository root when `python-dotenv` is available. The root `.env` is also read by Modal's `Secret.from_dotenv()` for remote transcription. The process changes its working directory to the repository root before Click parses command arguments, so relative input and output paths are resolved from that directory rather than the caller's current directory. Keep credentials out of command arguments and output paths.

The shared Click group also accepts these global options:

| Option | Description |
|--------|-------------|
| `--profile`, `-P` | Select a fast-market profile |
| `--verbose`, `-v` | Accepted by the shared CLI; this module currently keeps logging at `CRITICAL` |
| `--show-completion` | Print a shell completion script |
| `--install-completion` | Print completion installation instructions |

## CLI Reference

### Command overview

| Command | Description |
|---------|-------------|
| `video remove-silence INPUT` | Remove silent portions from a video |
| `video extract-transcript INPUT` | Create ASS, SRT, or TXT subtitles |
| `video burn-subtitles VIDEO ASS` | Burn ASS subtitles into a video |
| `video cut INPUT` | Trim a video at a timestamp using stream copy |
| `video concat INPUT... -o OUTPUT` | Concatenate two or more videos |
| `video duration INPUT` | Print a video duration in seconds |
| `video assemble IMAGE AUDIO` | Create a Ken Burns clip from an image and audio |
| `video pipeline INPUT` | Run silence removal, ASS transcription, and subtitle burn-in |
| `video modal-diagnose` | Check Modal connectivity and the remote environment |

### `video remove-silence INPUT_FILE`

Detect silent audio with an RMS threshold and write the remaining clips as H.264/AAC video.

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `INPUT_FILE` | — | Existing input video | required |
| `--output` | `-o` | Output path | `<stem>_nosilence<suffix>` next to the input |
| `--threshold` | `-t` | Silence threshold in dB | `-65.0` |
| `--modal` / `--local` | — | Run on Modal or locally | `--local` |

The local implementation fails if the input has no detectable non-silent audio or if the resulting video is not shorter than the source.

```bash
video remove-silence interview.mp4
video remove-silence interview.mp4 -o interview_compact.mp4 -t -55
video remove-silence interview.mp4 --modal
```

### `video extract-transcript INPUT_FILE`

Transcribe a video into karaoke-style ASS subtitles, SRT subtitles, or plain text.

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `INPUT_FILE` | — | Existing input video | required |
| `--output` | `-o` | Output path | `<stem>.<format>` next to the input |
| `--format` | `-f` | Output format: `ass`, `srt`, or `txt` | Inferred from the output extension, otherwise `srt` |
| `--language` | `-l` | Language code or `auto` | `fr` |
| `--model` | `-m` | Whisper model size | `medium` |
| `--font-size` | — | ASS font size | `96` |
| `--modal` / `--local` | — | Run on Modal or locally | `--local` |
| `--use-groq` | — | Use Groq `whisper-large-v3` instead of local `faster-whisper`; Modal SRT/TXT still use faster-whisper | off |

Format selection follows this order: explicit `--format`, output-file extension, then `srt`. ASS output uses word-level green/white highlighting; SRT and TXT contain segment-level or plain text. Local `--use-groq` supports all three formats, but the current Modal implementation uses Groq only for ASS; Modal SRT and TXT requests are transcribed with worker-side `faster-whisper`.

```bash
video extract-transcript talk.mp4
video extract-transcript talk.mp4 -o captions.ass -f ass -l en -m medium
video extract-transcript talk.mp4 -o captions.srt --font-size 72
video extract-transcript talk.mp4 --use-groq
video extract-transcript talk.mp4 --modal
```

### `video burn-subtitles VIDEO_FILE ASS_FILE`

Burn an ASS subtitle file into a video with ffmpeg.

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `VIDEO_FILE` | — | Existing input video | required |
| `ASS_FILE` | — | Existing ASS subtitle file | required |
| `--output` | `-o` | Output path | `<stem>_subtitled<suffix>` next to the video |
| `--font-size` | — | Subtitle font size | `96` |
| `--modal` / `--local` | — | Run on Modal or locally | `--local` |

```bash
video burn-subtitles talk.mp4 talk.ass
video burn-subtitles talk.mp4 talk.ass -o talk_subtitled.mp4 --font-size 72
video burn-subtitles talk.mp4 talk.ass --modal
```

### `video cut INPUT_FILE`

Trim at a timestamp with ffmpeg stream copy. This is fast, but the cut is not frame-accurate because the video is not re-encoded.

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `INPUT_FILE` | — | Existing input video | required |
| `--output` | `-o` | Output path | `<stem>_cut<suffix>` next to the input |
| `--time` | `-t` | Cut point as seconds, `MM:SS`, or `HH:MM:SS` | required |
| `--keep` | — | Keep `head` (`[0,time]`) or `tail` (`[time,end]`) | `head` |

```bash
video cut interview.mp4 -t 90
video cut interview.mp4 -t 1:30 --keep head
video cut interview.mp4 -t 00:01:30 --keep tail -o interview_tail.mp4
```

### `video concat INPUT_FILES... -o OUTPUT`

Concatenate at least two videos with a hard cut and no transition. Local processing re-encodes with H.264/AAC so source codecs and dimensions can differ.

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `INPUT_FILES...` | — | Two or more existing videos | at least 2 required |
| `--output` | `-o` | Output path | required |
| `--modal` / `--local` | — | Run on Modal or locally | `--local` |

```bash
video concat part-01.mp4 part-02.mp4 -o episode.mp4
video concat scene-a.mov scene-b.mov scene-c.mov -o scene.mp4 --modal
```

### `video duration INPUT_FILE`

Print the duration reported by `ffprobe`, formatted to three decimal places.

```bash
video duration interview.mp4
```

### `video assemble IMAGE_FILE AUDIO_FILE`

Create a 1280×720 H.264/AAC MP4 from a still image and an audio file. The clip duration matches the audio duration.

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `IMAGE_FILE` | — | Existing still image | required |
| `AUDIO_FILE` | — | Existing audio file | required |
| `--output` | `-o` | Output MP4 path | `<audio_stem>_clip.mp4` next to the audio |
| `--motion` | `-m` | Ken Burns profile: `random`, named zoom/pan profiles, or `*_random` profiles | `random` |
| `--zoom-from` | — | Start zoom fallback | `1.0` |
| `--zoom-to` | — | End zoom fallback | `1.3` |
| `--fps` | — | Output frame rate | `24` |
| `--format` | `-F` | Output: `text` or `json` | `text` |

Available motion values are `random`, `zoom_in`, `zoom_out`, `zoom_in_tl`, `zoom_in_tr`, `zoom_in_bl`, `zoom_in_br`, `pan_right`, `pan_left`, `pan_up`, `pan_down`, `drift_tl`, `drift_tr`, `zoom_in_random`, `zoom_out_random`, and `zoom_random`.

The supported motion profiles currently define their own zoom and pan values. The `--zoom-from` and `--zoom-to` options are accepted as fallback values, but they do not override a supported profile in the current implementation.

```bash
video assemble title.png narration.wav
video assemble title.png narration.wav -m zoom_in -o scene.mp4
video assemble title.png narration.wav --format json | jq '.path'
```

JSON output contains the output path, audio duration, and probed dimensions:

```json
{
  "path": "/absolute/path/scene.mp4",
  "duration_secs": 42.75,
  "width": 1280,
  "height": 720
}
```

### `video pipeline INPUT_FILE`

Run the complete local or remote sequence:

1. Remove silence and write an intermediate MP4.
2. Generate an ASS transcript from the intermediate video.
3. Burn the ASS subtitles into the final MP4.

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `INPUT_FILE` | — | Existing input video | required |
| `--output` | `-o` | Final subtitled output path | `<stem>_subtitled.mp4` in the work directory |
| `--workdir` | — | Directory for intermediate files | Input directory |
| `--threshold` | `-t` | Silence threshold in dB | `-65.0` |
| `--language` | `-l` | Language code or `auto` | `fr` |
| `--model` | `-m` | Whisper model size | `medium` |
| `--font-size` | — | Subtitle font size | `96` |
| `--modal` / `--local` | — | Run all media steps on Modal or locally | `--local` |

The pipeline always creates ASS subtitles and does not expose `extract-transcript`'s `--use-groq` option. Use the granular commands when a caller needs independent retry, resume, or format boundaries.

```bash
video pipeline source.mp4
video pipeline source.mp4 --workdir ./publish-work -o ./publish-work/final.mp4
video pipeline source.mp4 --modal --language auto
```

### `video modal-diagnose`

Check Modal connectivity and inspect the Python, ffmpeg, `faster-whisper`, and MoviePy versions available in the remote image.

| Option | Description | Default |
|--------|-------------|---------|
| `--full` | Also upload a clip, remux it with ffmpeg, and run the media pipeline with the `tiny` Whisper model | off |
| `--clip` | Clip used by `--full` | `video-cli/tests/fixtures/publish/test_clip.mkv` |

The full diagnostic writes downloaded MP4 and ASS files to temporary local paths and reports those paths.

```bash
video modal-diagnose
video modal-diagnose --full
video modal-diagnose --full --clip ./fixtures/short.mp4
```

## Local and Modal Processing

Local processing is the default. Add `--modal` to commands that support remote execution.

| Command | Local | Modal |
|---------|-------|-------|
| `remove-silence` | yes | yes |
| `extract-transcript` | yes | yes |
| `burn-subtitles` | yes | yes |
| `concat` | yes | yes |
| `pipeline` | yes | yes |
| `cut` | yes | no |
| `duration` | yes | no |
| `assemble` | yes | no |
| `modal-diagnose` | remote diagnostic | yes |

Modal commands serialize input files as bytes and write returned bytes to the requested output path. The granular remote commands use the shared Modal application and can be cancelled when the local process receives `SIGINT` or `SIGTERM`; the combined `video pipeline --modal` path uses one remote function for the complete sequence. See [ADR 010](../_doc/adr/010-modal-remote-processing.md) for the transport and resume decisions.

## Scripting Contract

Status and progress messages are written to stderr. Machine-readable results and final output paths are written to stdout:

```bash
duration="$(video duration input.mp4)"
no_silence="$(video remove-silence input.mp4)"
ass="$(video extract-transcript "$no_silence" -f ass)"
final="$(video burn-subtitles "$no_silence" "$ass")"
printf '%s\n' "$final"
```

`video duration` emits only a numeric value such as `12.345`. `video assemble --format json` emits one JSON object. Do not parse the status lines on stderr as command results.

Most commands do not create missing parent directories for an explicit output path; create the directory first. `video pipeline --workdir` does create its work directory.

## Architecture

```text
video_entry/__init__.py
        |
        v
cli/main.py ---> common.cli.base ---> common.core.registry
        |
        v
commands/<command>/register.py
        |
        +--> local implementation (ffmpeg, MoviePy, faster-whisper, Pillow)
        |
        +--> commands/remote.py ---> modal_client/app.py
                                      |
                                      +--> modal_client/remote_steps.py
                                      +--> modal_client/diagnose.py
```

Commands are auto-discovered from `commands/*/register.py`. Each registration returns a `CommandManifest`, whose Click command is attached to the root `video-agent` group. The `common/` directory is a symlink to the shared fast-market utilities.

The Modal implementation intentionally keeps worker-side helpers in `modal_client/remote_steps.py` instead of mounting the repository. Changes to local silence removal, transcription, subtitle burning, or concatenation must be reviewed against the corresponding remote helpers.

## Integrations

The `webux-cli` publishing workflows use the granular commands so each processing stage can be retried or resumed independently:

- `webux-cli/webux/short_publish/pipeline.py` invokes `video cut`, `video remove-silence`, `video extract-transcript`, `video burn-subtitles`, and `video concat`.
- `webux-cli/webux/long_publish/pipeline.py` invokes silence removal, transcription, and concatenation.
- `webux-cli/webux/short_publish/utils.py` invokes `video duration`.
- `webux-cli/webux/storyboard/pipeline.py` invokes `video assemble`.

## Features

- RMS-based silence removal with configurable threshold
- Local transcription to ASS, SRT, or TXT
- Optional Groq transcription
- ASS subtitle burn-in through ffmpeg
- Fast stream-copy trimming
- MoviePy concatenation with re-encoding
- Image-plus-audio Ken Burns assembly
- Combined pipeline with local or Modal execution
- Script-friendly stdout and stderr separation
- Modal environment and transfer diagnostics

## Troubleshooting

### `ffmpeg` or `ffprobe` is not found

Install the system FFmpeg tools and ensure both binaries are on `PATH`. `cut`, `duration`, subtitle burn-in, and the Groq audio conversion invoke these binaries directly.

### A media test reports `ModuleNotFoundError`

The local media implementations import `moviepy` and `faster_whisper` at operation time. Install the `video-cli` dependencies with the editable install command before running the full suite. `assemble` also imports Pillow, so ensure that package is installed when using that command.

### `Silent video — no non-silent segments detected`

The input has no audio above the selected RMS threshold, or its audio cannot be decoded. Confirm the input has an audio track, then adjust `--threshold` for the recording.

### `Output video ... is not shorter than input`

The local implementation found no useful reduction. Try another threshold or use the unprocessed source if the recording contains no removable silence.

### Subtitle output is empty or malformed

Check that the video has usable audio, that `--language` matches the speech, and that the selected Whisper model is installed or can be downloaded. For burn-in, pass the ASS file produced with `--format ass`.

### `GROQ_API_KEY environment variable not set`

Set `GROQ_API_KEY` in the environment or repository `.env` before using local `--use-groq`. For Modal execution, the key must be available to the Modal secret loaded from the repository `.env` when requesting ASS output; Modal SRT and TXT requests currently use worker-side `faster-whisper` instead.

### Modal authentication or remote execution fails

Run `modal setup`, then run `video modal-diagnose`. Use `video modal-diagnose --full` only after the basic environment check succeeds. Remote processing transfers the complete input as bytes and can take time during a cold start.

### The output file cannot be written

Create the parent directory before passing an explicit `-o/--output` path. The pipeline's `--workdir` is the exception because it creates the directory itself.

### Local and Modal results differ

The remote worker uses a duplicated implementation by design. Compare the local command with the matching helper in `modal_client/remote_steps.py` and update both paths when changing processing behavior.

## Development and Testing

From the repository root, run the video test suite explicitly:

```bash
pytest video-cli/tests/ -v
```

Or run it from the package directory:

```bash
cd video-cli
pytest tests/
```

The current tests cover cut timestamp parsing and stream-copy behavior, duration probing, ASS generation, silence removal, and subtitle-burn regressions. Golden fixtures can be regenerated with:

```bash
pytest video-cli/tests/test_publish_regression.py --generate-golden
```

Regeneration overwrites committed fixtures and may invoke a real Whisper model; use it only for an intentional behavior change. There is no video-specific lint or typecheck command configured in this repository.

To inspect the installed command surface after an editable install:

```bash
video --help
video <command> --help
```

## Related Documentation

- See [`AGENTS.md`](AGENTS.md) for contributor architecture, integration boundaries, pitfalls, and extension points.
- See [`../_doc/adr/010-modal-remote-processing.md`](../_doc/adr/010-modal-remote-processing.md) for the Modal transport and resume design.
- See [`../common/core/registry.py`](../common/core/registry.py) for command discovery.
- See [`../common/cli/base.py`](../common/cli/base.py) for shared global CLI options.
