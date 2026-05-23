# youtube-agent

YouTube CLI tool for searching videos, fetching comments, posting replies, and publishing YouTube Shorts via the YouTube Data API v3. Includes a media processing pipeline (silence removal, transcription, subtitle burning) that can run locally or remotely on Modal.

## Installation

```bash
cd youtube-cli
pip install -e .
```

### Prerequisites
- Python 3.11+
- Google Cloud Project with YouTube Data API v3 enabled
- OAuth 2.0 credentials (`client_secret.json`)
- `ffmpeg` installed locally (for media processing commands)

## Configuration

The tool follows XDG specifications for configuration:
- Config: `~/.config/fast-market/common/youtube/config.yaml`
- Cache: `~/.cache/youtube-videos/`
- OAuth token: `~/.config/fast-market/common/youtube/token.json`
- Client secrets: `~/.config/fast-market/common/youtube/client_secret.json`

### First-time Setup

```bash
youtube setup wizard
```

This creates a default configuration at `~/.config/fast-market/common/youtube/config.yaml`.

### Getting Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project or select existing one
3. Enable **YouTube Data API v3**
4. Go to **Credentials** → **Create Credentials** → **OAuth client ID**
   - Application type: Desktop application
5. Download the JSON file and save as `client_secret.json`:
   ```bash
   mv ~/Downloads/client_secret.json ~/.config/fast-market/common/youtube/
   ```

### Verify Setup

```bash
youtube setup locate
youtube setup show
youtube search "test"   # triggers OAuth on first run
```

---

## CLI Reference

### setup

```bash
youtube setup [COMMAND]
```

**Commands:** `edit`, `show`, `locate`, `wizard`, `reset`, `refresh-auth`, `channel-list`

---

### search

```bash
youtube search KEYWORDS... [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-n, --max-results` | Number of results | 10 |
| `--order` | date / relevance / rating / title / viewCount | relevance |
| `--language` | Language code | en |
| `--combine` | OR instead of AND for keywords | False |
| `-f, --format` | json / yaml / text | text |
| `-o, --output` | Save to file | None |
| `--use-yt-dlp` | Use yt-dlp instead of YouTube API | False |

---

### get-last

Get the last video from your channel.

```bash
youtube get-last [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--short` | Shorts only (≤3min) | False |
| `--normal` | Normal videos only (>3min) | False |
| `-n, --offset` | Nth from last | 1 |
| `-c, --channel-id` | Override channel ID | mine |
| `--short-threshold` | Duration threshold in seconds | 180 |

**Output:** Two lines — title and URL.

---

### get-video

Download a YouTube video.

```bash
youtube get-video URL [OPTIONS]
youtube get-video --last [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--last` | Get last video from channel | False |
| `--short` / `--normal` | Filter type when using --last | — |
| `-n, --offset` | Nth from last | 1 |
| `-o, --output` | Output file path | auto |
| `--lookup-dir` | Cache directory | ~/.cache/youtube-videos |
| `--cookies` | Cookies file for authenticated requests | None |

---

### comments / batch-comments

```bash
youtube comments [VIDEO_ID] [OPTIONS]
youtube batch-comments INPUT_FILE [OPTIONS]
```

Fetch comments for one or many videos. `batch-comments` reads a JSON/YAML file of video IDs.

---

### batch-comment-reply

Generate LLM-powered replies for a list of comments.

```bash
youtube batch-comment-reply INPUT_FILE [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-p, --prompt` | Prompt template (repeatable). Supports `@filename`, `{URL}`, `{AUTHOR}`, `{COMMENT}` |
| `-s, --shell` | Shell command to generate replies instead of LLM |
| `--rewrite` | Regenerate only `--filter` IDs, keep others |
| `-o, --output` | Output file |

---

### batch-comment-post

Post generated replies to YouTube.

```bash
youtube batch-comment-post INPUT_FILE [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--dry-run` | Preview without posting | False |
| `-d, --delay` | Seconds between posts | 0 |

---

### reply

Post a single reply to a YouTube comment.

```bash
youtube reply COMMENT_ID TEXT
```

---

### remove-silence

Remove silent segments from a video using RMS-based detection (moviepy).

```bash
youtube remove-silence INPUT_FILE [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-o, --output` | Output file | `{stem}_nosilence{ext}` |
| `-t, --threshold` | Silence threshold in dB | -65.0 |

**Output:** Path to the processed video on stdout.

---

### extract-transcript

Transcribe a video to ASS karaoke subtitles, SRT, or plain text using faster-whisper.

```bash
youtube extract-transcript INPUT_FILE [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-o, --output` | Output file (extension infers format) | `{stem}.srt` |
| `-f, --format` | ass / srt / txt | inferred from extension |
| `-l, --language` | Language code or `auto` | fr |
| `-m, --model` | Whisper model size | medium |
| `--font-size` | ASS font size (ASS only) | 96 |

**ASS format** produces word-level karaoke highlighting (green = current word, white = upcoming).

---

### burn-subtitles

Burn an ASS subtitle file into a video using ffmpeg.

```bash
youtube burn-subtitles VIDEO_FILE ASS_FILE [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-o, --output` | Output file | `{stem}_subtitled{ext}` |
| `--font-size` | Subtitle font size | 96 |

---

### modal-diagnose

Test Modal API connectivity and the remote processing environment.

```bash
youtube modal-diagnose [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--full` | Run file roundtrip + full media pipeline on a test clip |
| `--clip PATH` | Clip to use for `--full` (default: built-in 6s fixture) |

**Requires:** Modal authentication (`modal token new`).

`--full` runs three steps:
1. Environment check: Python version, ffmpeg, faster-whisper, moviepy
2. File roundtrip: upload clip → ffmpeg remux MKV→MP4 → download
3. Full pipeline: silence removal + whisper transcription (tiny model) + subtitle burning

---

## Publish Pipeline (webux)

The publish pipeline is exposed as a webux plugin tab ("Publish") and orchestrates the full Shorts production workflow:

```
Remove silence → Extract transcript → Burn subtitles → Generate title & description → Upload to YouTube → Post-publish script
```

### Pipeline steps

| Step | Tool | Description |
|------|------|-------------|
| 0. Remove silence | moviepy | RMS-based silence removal |
| 1. Extract transcript | faster-whisper | ASS karaoke subtitle generation |
| 2. Burn subtitles | ffmpeg | Hardcoded subtitles into video |
| 3. Generate title & description | LLM (prompt-cli) | Runs two prompt templates against transcript |
| 4. Upload to YouTube | youtube upload | Uploads final video |
| 5. Post-publish script | bash | Optional script receiving the final video path |

Steps 0-2 can run **remotely on Modal** when "Use Modal" is checked in the UI. Steps 3-5 always run locally.

### Modal remote processing

When enabled, steps 0-2 are executed in a single Modal container call (`run_media_pipeline` in `modal_client/remote_steps.py`). The source video is serialized as bytes, sent to Modal, processed, and the output video + ASS file are written back to the video source directory.

See `_doc/adr/010-modal-remote-processing.md` for the full design rationale.

### Publish config

Stored under the `publish` key in `~/.config/fast-market/common/youtube/config.yaml`:

```yaml
youtube:
  publish:
    video_source_path: /home/user/Videos
    video_extensions: mp4,mkv
    default_title_prompt: youtube-title
    default_description_prompt: youtube-summary
    language: fr
    model: medium
    privacy: unlisted
    signature: ""
    post_publish_script: ""
    modal_usage_url: https://modal.com/settings/usage
```

---

## Architecture

```
youtube-cli/
├── youtube_entry/          # Entry point — exports main()
├── cli/
│   └── main.py             # Click CLI group + command discovery
├── core/
│   ├── config.py           # Config loading
│   └── engine.py           # YouTube client factory
├── commands/               # Auto-discovered plugin commands
│   ├── base.py             # CommandManifest dataclass
│   ├── search/
│   ├── get_last/
│   ├── get_video/
│   ├── comments/
│   ├── batch_extract_comments/
│   ├── batch_comment_post/
│   ├── batch_transcript/
│   ├── reply/
│   ├── channels/
│   ├── hot/
│   ├── stats/
│   ├── upload/
│   ├── remove_silence/     # moviepy silence removal
│   ├── extract_transcript/ # faster-whisper ASS/SRT/TXT transcription
│   ├── burn_subtitles/     # ffmpeg subtitle burning
│   ├── modal_diagnose/     # Modal connectivity test
│   └── setup/
├── modal_client/           # Modal remote processing package
│   ├── app.py              # modal.App + base_image (ffmpeg + whisper + moviepy)
│   ├── diagnose.py         # Remote environment check functions
│   └── remote_steps.py     # run_media_pipeline() — all 3 media steps in one container
├── webux/
│   └── publish/
│       ├── models.py       # Job, Step dataclasses
│       ├── pipeline.py     # Async pipeline orchestration (local + Modal paths)
│       ├── pool.py         # Job queue management
│       ├── register.py     # FastAPI router + webux plugin registration
│       ├── utils.py        # Config, meta, ffprobe helpers
│       └── frontend.html   # Single-page publish UI
└── tests/
    └── fixtures/
        └── publish/
            └── test_clip.mkv   # 6s test clip used by modal-diagnose --full
```

### Command discovery

All commands in `commands/` are auto-discovered at startup by `common.core.registry.discover_commands()`. Each command directory must contain a `register.py` with a `register(plugin_manifests) -> CommandManifest` function.

### Adding a new command

```python
# commands/my_command/register.py
import click
from commands.base import CommandManifest

def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("my-command")
    def cmd():
        """Description."""
        pass
    return CommandManifest(name="my-command", click_command=cmd)
```

No further registration needed — the command is discovered automatically.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `click` | CLI framework |
| `pyyaml` | Config files |
| `pydantic` | Request/response models |
| `google-api-python-client` | YouTube Data API v3 |
| `google-auth-oauthlib` | OAuth flow |
| `yt-dlp` | Advanced video downloading |
| `numpy` | Audio array processing (silence detection) |
| `moviepy` | Video editing (silence removal) |
| `faster-whisper` | Local speech-to-text transcription |
| `modal` | Remote serverless compute |
