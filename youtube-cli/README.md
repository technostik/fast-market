# youtube-agent

YouTube CLI tool for searching videos, fetching comments, and posting replies via the YouTube Data API v3.

## Installation

```bash
# Clone and install
cd youtube-agent
pip install -e .

# Install with yt-dlp support for advanced searching
pip install -e ".[ytdlp]"
```

### Prerequisites
- Python 3.11+
- Google Cloud Project with YouTube Data API v3 enabled
- OAuth 2.0 credentials (client_secret.json)

## Configuration

The tool follows XDG specifications for configuration:
- Config: `~/.config/fast-market/common/youtube/config.yaml`
- Cache: `~/.cache/youtube-videos/` (for video caching)
- OAuth token: `~/.config/fast-market/common/youtube/token.json`
- Client secrets: `~/.config/fast-market/common/youtube/client_secret.json`

### First-time Setup

Run the interactive setup wizard:
```bash
youtube setup wizard
```

This creates a default configuration at `~/.config/fast-market/common/youtube/config.yaml`:

```yaml
# YouTube shared configuration
channel_id: ""
quota_limit: 10000
video_cache_dir: ~/.cache/youtube-videos
# client_secret_path: ~/.config/fast-market/common/youtube/client_secret.json
```

### Getting Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project or select existing one
3. Enable **YouTube Data API v3**
4. Go to **Credentials** → **Create Credentials** → **OAuth client ID**
   - Application type: Desktop application
   - Name: youtube-agent
 5. Download the JSON file and save as `client_secret.json` in the config directory:
    ```bash
    mv ~/Downloads/client_secret.json ~/.config/fast-market/common/youtube/
    ```

### Verify Setup

```bash
# Check configuration
youtube setup locate
youtube setup show

# Edit configuration if needed
youtube setup edit

# Test authentication (will open browser for OAuth)
youtube search "test"
```

## CLI Reference

### get-last

Get the last video from your channel with optional filtering by type.

```bash
youtube get-last [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--short` | Filter to YouTube Shorts only (duration <= 3min) | False |
| `--normal` | Filter to normal videos only (duration > 3min) | False |
| `-n, --offset` | Get the Nth from last (1=last, 2=2nd from last, etc.) | 1 |
| `-c, --channel-id` | Override channel ID (defaults to authenticated user's channel) | mine |
| `--short-threshold` | Duration threshold in seconds for short detection | 180 (3min) |
| `--debug` | Show debug information | False |

**Examples:**
```bash
# Get the last video (most recent)
youtube get-last

# Get the last Short (≤3min)
youtube get-last --short

# Get the last normal video (>3min)
youtube get-last --normal

# Get the 2nd last short
youtube get-last --short -n 2

# Get the 3rd last video overall
youtube get-last -n 3

# Use custom threshold (1 minute for older shorts)
youtube get-last --short --short-threshold 60

# Specify a different channel
youtube get-last --channel-id UCxxxxxxx

# Debug output to see what's happening
youtube get-last --short --debug
```

**Output:** Two lines - video title and URL.

### get-video

Download YouTube videos using yt-dlp with optional caching and lookup.

```bash
youtube get-video URL [OPTIONS]
youtube get-video --last [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--last` | Get the last video from channel instead of specifying URL | False |
| `-c, --channel-id` | YouTube channel ID (required for --last, defaults to config) | None |
| `--short` | Filter to YouTube Shorts only when using --last | False |
| `--normal` | Filter to normal videos only when using --last | False |
| `-n, --offset` | Get the Nth from last when using --last | 1 |
| `--short-threshold` | Duration threshold in seconds for short detection | 180 (3min) |
| `--debug` | Show debug information | False |
| `--lookup-dir` | Directory to search for cached videos | ~/.cache/youtube-videos |
| `-o, --output` | Save video to specific file | Auto-generated from title |
| `--cookies` | Path to cookies file for authenticated requests | None |

**Examples:**
```bash
# Download a specific video
youtube get-video "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Get and download the last video from your channel
youtube get-video --last

# Get the last short video
youtube get-video --last --short

# Get the 2nd last normal video
youtube get-video --last --normal --offset 2

# Download to specific location
youtube get-video --last --output "/path/to/video.mp4"

# Use custom cache directory
youtube get-video --last --lookup-dir "/custom/cache/dir"
```

### setup

Manage configuration and authentication with various subcommands.

```bash
youtube setup [COMMAND] [OPTIONS]
```

**Commands:**
- `edit` - Open YouTube config in your default editor
- `show` - Display current configuration
- `locate` - Show config file locations and status
- `wizard` - Interactive setup wizard
- `reset` - Reset config to defaults (backs up existing)
- `refresh-auth` - Re-authenticate with full API access
- `channel-list` - Manage channel list file

**Examples:**
```bash
# Edit configuration in editor
youtube setup edit

# Interactive setup
youtube setup wizard

# Check setup status
youtube setup locate

# View current config
youtube setup show

# Reset to defaults
youtube setup reset
```

### search

Search for YouTube videos by keywords.

```bash
youtube search KEYWORDS... [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-n, --max-results` | Number of results | 10 |
| `--order` | Sort order: date, relevance, rating, title, viewCount | relevance |
| `--language` | Language code (e.g., en, fr, es) | en |
| `--combine` | Use OR instead of AND for keywords | False |
| `-f, --format` | Output: json, yaml, text | text |
| `-o, --output` | Save results to file | None |
| `--stdin` | Read video IDs from stdin for filtering | False |
| `--use-yt-dlp` | Use yt-dlp instead of YouTube API (requires yt-dlp) | False |

**Examples:**
```bash
# Basic search
youtube search "python tutorial" -n 5

# Sort by date, French language
youtube search "tutoriel python" --order date --language fr -n 3

# OR search
youtube search "python java" --combine

# Output as JSON to file
youtube search "machine learning" --format json -o results.json

# Use yt-dlp for more flexible searching
youtube search "site:youtube.com tutorial" --use-yt-dlp

# Filter search results by video IDs from stdin
echo '{"video_id": "dQw4w9WgXcQ"}' | youtube search --stdin
```

### comments

Fetch comments for YouTube videos.

```bash
youtube comments [VIDEO_ID] [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-n, --max-results` | Maximum comments per video | 20 |
| `--order` | Sort order: relevance, time | relevance |
| `-f, --format` | Output: json, yaml, text | text |
| `-o, --output` | Save results to file | None |
| `--stdin` | Read video IDs from stdin | False |
| `--field` | JSON field to extract IDs from stdin | video_id |

**Examples:**
```bash
# Get comments for a video
youtube comments dQw4w9WgXcQ -n 10

# Sort by newest first
youtube comments dQw4w9WgXcQ --order time

# Chain with search using jq
youtube search "tutorial" -n 3 --format json \
  | jq '.[].id' -r \
  | xargs -I {} youtube comments {} -n 5

# Using stdin with custom field
echo '[{"video": "dQw4w9WgXcQ"}]' | youtube comments --stdin --field video
```

### batch-comments

Extract comments from multiple videos listed in a JSON/YAML file.

```bash
youtube batch-comments INPUT_FILE [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-n, --limit` | Maximum comments per video | 5 |
| `--order` | Sort order: relevance, time | relevance |
| `-f, --format` | Output: json, yaml, text | text |
| `-o, --output` | Save results to file | None |
| `--field` | JSON field to extract video IDs | video_id |

**Examples:**
```bash
# Extract comments from search results
youtube search "python tutorial" -n 3 --format json -o videos.json
youtube batch-comments videos.json -n 5 --format json -o comments.json
```

### batch-comment-reply

Generate replies to comments from a batch-comments output file. Supports two modes:
- **LLM mode**: Uses an LLM to generate replies (default)
- **Shell mode**: Uses a custom shell command to generate replies

```bash
youtube batch-comment-reply INPUT_FILE [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-p, --prompt` | Prompt template for LLM mode. Can be used multiple times. Supports `@filename`, `@-` for stdin, and template variables `{URL}`, `{AUTHOR}`, `{COMMENT}` | - |
| `-s, --shell` | Shell command to generate replies. Receives comment via env vars: AUTHOR, COMMENT, VIDEO_URL, VIDEO_ID, VIDEO_TITLE, COMMENT_ID | - |
| `-m, --metadata` | Key-value pairs to include in output (repeatable). Format: `key=value` | - |
| `--filter` | JSON list of comment IDs to process (in rewrite mode: IDs to regenerate) | - |
| `--rewrite` | Rewrite output file: regenerate filtered IDs, keep others. Requires --filter and --output | - |
| `-f, --format` | Output: json, yaml, text | json |
| `-o, --output` | Save results to file | stdout |

**LLM Mode (default):**

```bash
# Simple reply generation
youtube batch-comment-reply comments.json \
  -p "Write a friendly, helpful reply to this YouTube comment" \
  --format json -o replies.json

# Multiple prompts with file reference
youtube batch-comment-reply comments.json \
  -p 'Write a response that agrees with the comment and promotes my video {URL}.' \
  -p 'Use this transcript for context: @transcript.txt' \
  -o replies.json
```

**Shell Mode:**

```bash
# Using prompt CLI to generate replies
youtube batch-comment-reply comments.json \
  -s 'prompt get my-prompt --content | claude --no-stream' \
  -m prompt_name=my-prompt \
  -o replies.json

# Using custom script
youtube batch-comment-reply comments.json \
  -s './generate_reply.sh' \
  -m source=custom \
  -o replies.json
```

**Environment variables in shell mode:**
- `AUTHOR` - Comment author name
- `COMMENT` or `COMMENT_TEXT` - The comment text
- `VIDEO_URL` - URL of the video
- `VIDEO_ID` - YouTube video ID
- `VIDEO_TITLE` - Video title
- `COMMENT_ID` - YouTube comment ID

**Output format:**
```json
[
  {
    "video_url": "https://www.youtube.com/watch?v=...",
    "original_comment": { ... },
    "reply": "Generated reply text...",
    "metadata": { "prompt_name": "my-prompt" },
    "error": null  // present if shell command failed
  }
]
```

**Rewrite Mode (regenerate specific replies):**

```bash
# Regenerate specific replies in existing file
youtube batch-comment-reply replies.json \
  --filter '["comment_id_1", "comment_id_2"]' \
  --rewrite \
  -o replies.json \
  -p "New prompt for regeneration"

# Regenerate all replies (requires --filter to list all IDs)
youtube batch-comment-reply replies.json \
  --filter '["all_ids_from_file"]' \
  --rewrite \
  -o replies.json \
  -p "New prompt"
```

**Rewrite mode:**
- Reads existing output file (specified as INPUT_FILE)
- Regenerates only the replies matching `--filter` IDs
- Writes merged results to `--output` file
- Preserves non-regenerated entries unchanged

### batch-comment-post

Post LLM-generated replies to YouTube comments from a batch-comment-reply output file.

```bash
youtube batch-comment-post INPUT_FILE [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--dry-run` | Preview replies without posting | False |
| `-d, --delay` | Seconds to wait between each post | 0 |
| `-f, --format` | Output: json, yaml, text | json |
| `-o, --output` | Update input file with reply status | None |

**Examples:**
```bash
# Preview what would be posted
youtube batch-comment-post replies.json --dry-run

# Post replies with 2s delay between each
youtube batch-comment-post replies.json --delay 2 -o posted_results.json
```

### reply

Generate reply text for YouTube comments. Use `batch-comment-post` to actually post replies to YouTube.

```bash
youtube reply [COMMENT_ID] [TEXT] [OPTIONS]
```

**Parameters:**

| Parameter | Description |
|-----------|-------------|
| `COMMENT_ID` | YouTube comment ID to reply to (required unless using --from-file or --stdin) |
| `TEXT` | Reply text to post (required unless using --from-file or --stdin) |

**Options:**

| Option | Description |
|--------|-------------|
| `--from-file` | JSON/YAML file containing array of `{comment_id, text}` objects |
| `-f, --format` | Output format: `json`, `yaml`, or `text` (default: `text`) |
| `-o, --output` | Save results to file instead of stdout |
| `--stdin` | Read input from stdin (JSON array of `{comment_id, text}` objects) |

**Examples:**
```bash
# Generate a single reply
youtube reply COMMENT_ID "Thanks for watching!"

# Batch generate replies from file
youtube reply --from-file replies.json

# replies.json format:
# [
#   {"comment_id": "abc123", "text": "Great point!"},
#   {"comment_id": "def456", "text": "Agreed!"}
# ]

# Pipe from comments command
youtube comments VIDEO_ID -n 5 --format json \
  | jq '.[] | {comment_id: .id, text: "Thanks!"}' \
  | youtube reply --stdin
```

**Output:** Generated reply objects with `comment_id` and `text` (use `batch-comment-post` to post to YouTube)

## Features

### Quota Tracking
- Automatically tracks YouTube API quota usage
- Default limit: 10,000 units/day (YouTube Data API standard)
- Quota persists across sessions in `~/.cache/fast-market/youtube/quota.json`
- Prevents accidental quota exhaustion

### Piping Support
All commands support JSON/YAML streaming for pipeline composition:

```bash
# Full batch workflow: search → extract comments → generate replies → post
youtube search "tutorial" -n 3 --format json -o videos.json
youtube batch-comments videos.json -n 5 --format json -o comments.json
youtube batch-comment-reply comments.json \
  -p "Write a friendly, helpful reply" \
  --format json -o replies.json
youtube batch-comment-post replies.json --dry-run              # Preview first
youtube batch-comment-post replies.json --delay 2 -o results.json

# Multi-stage pipeline
youtube search "tutorial" -n 5 --format json \
  | youtube comments --stdin -n 3 \
  | youtube reply --stdin

# Extract and transform with jq
youtube search "python" --format json \
  | jq '.[] | {id, title, channel_title}' \
  > summary.json
```

### Multiple Input Formats
- JSON files
- YAML files
- stdin (auto-detects JSON/YAML)
- Direct arguments

### Error Handling
- Clear error messages for configuration issues
- OAuth flow failure recovery
- API quota exceeded warnings

## Architecture

```
youtube-agent/
├── youtube_entry/       # CLI entry point
│   └── __init__.py      # Exports main()
├── cli/
│   └── main.py          # Click CLI group
├── core/
│   ├── config.py        # Config loading
│   └── engine.py        # YouTube client factory
├── commands/            # Plugin-style commands
│   ├── base.py          # CommandManifest
│   ├── batch_comments/
│   │   └── register.py  # Batch comments extraction
│   ├── batch_comment_reply/
│   │   └── register.py  # LLM-powered reply generation
│   ├── batch_comment_post/
│   │   └── register.py  # Batch posting to YouTube
│   ├── search/
│   │   └── register.py  # Search implementation
│   ├── comments/
│   │   └── register.py  # Comments implementation
│   ├── reply/
│   │   └── register.py  # Reply implementation
│   ├── get_last/
│   │   └── register.py  # Get last video implementation
│   └── setup/
│       └── register.py  # Setup command
└── common/              # Shared utilities (symlink)
    ├── youtube/
    │   ├── client.py    # YouTube API wrapper
    │   ├── models.py    # Pydantic models
    │   └── quota.py     # Quota tracking
    └── auth/
        └── youtube.py   # OAuth handling
```

## Development

### Adding New Commands

1. Create a new directory in `commands/your_command/`
2. Create `register.py` with:
   ```python
   from commands.base import CommandManifest
   import click
   
   def register(plugin_manifests: dict) -> CommandManifest:
       @click.command("your-command")
       def cmd():
           """Your command description."""
           pass
       
       return CommandManifest(
           name="your-command",
           click_command=cmd,
       )
   ```

3. Command automatically discovered on next run

### Testing

```bash
# Run tests (if available)
pytest tests/

# Test with debug logging
YOUTUBE_DEBUG=1 youtube search test
```

### Dependencies
- `click>=8.1` - CLI framework
- `pyyaml>=6.0` - YAML support
- `pydantic>=2.0` - Data validation
- `google-api-python-client>=2.0` - YouTube API
- `google-auth-oauthlib>=1.0` - OAuth flow
- `yt-dlp` (optional) - Advanced searching
