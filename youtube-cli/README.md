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
- Config: `~/.local/share/fast-market/config/youtube-agent.yaml`
- Cache: `~/.cache/fast-market/youtube/` (for quota tracking)
- OAuth token: `~/.local/share/fast-market/config/token.json`

### First-time Setup

Run the interactive setup wizard:
```bash
youtube setup --create
```

This creates a default configuration at `~/.local/share/fast-market/config/youtube-agent.yaml`:

```yaml
# YouTube agent configuration
youtube:
  # Get your channel ID from YouTube Studio > Settings > Channel
  # Or use any channel ID you want to interact with
  channel_id: ""

  # Quota limit (default: 10000 units/day)
  quota_limit: 10000

  # Optional: explicit path to client_secret.json
  # If not specified, looks for client_secret.json in config directory
  # client_secret_path: "~/.config/fast-market/config/client_secret.json"
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
   mv ~/Downloads/client_secret.json ~/.local/share/fast-market/config/
   ```

### Verify Setup

```bash
# Check configuration
youtube setup --locate
youtube setup --show

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

### setup

Manage configuration and authentication.

```bash
youtube setup [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-l, --locate` | Show config file locations and status |
| `-s, --show` | Display current configuration |
| `-c, --create` | Create default configuration file |

**Examples:**
```bash
# Create initial config
youtube setup --create

# Check setup status
youtube setup --locate

# View current config
youtube setup --show
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

### batch-reply

Generate replies to comments from a batch-comments output file. Supports two modes:
- **LLM mode**: Uses an LLM to generate replies (default)
- **Shell mode**: Uses a custom shell command to generate replies

```bash
youtube batch-reply INPUT_FILE [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-p, --prompt` | Prompt template for LLM mode. Can be used multiple times. Supports `@filename`, `@-` for stdin, and template variables `{URL}`, `{AUTHOR}`, `{COMMENT}` | - |
| `-s, --shell` | Shell command to generate replies. Receives comment via env vars: AUTHOR, COMMENT, VIDEO_URL, VIDEO_ID, VIDEO_TITLE, COMMENT_ID | - |
| `-m, --metadata` | Key-value pairs to include in output (repeatable). Format: `key=value` | - |
| `--filter` | JSON list of comment IDs to process (in rewrite mode: IDs to regenerate) | - |
| `--rewrite` | Rewrite existing output file: regenerate filtered IDs, keep others. Requires --filter. Cannot use with --output | - |
| `-f, --format` | Output: json, yaml, text | json |
| `-o, --output` | Save results to file | stdout |

**LLM Mode (default):**

```bash
# Simple reply generation
youtube batch-reply comments.json \
  -p "Write a friendly, helpful reply to this YouTube comment" \
  --format json -o replies.json

# Multiple prompts with file reference
youtube batch-reply comments.json \
  -p 'Write a response that agrees with the comment and promotes my video {URL}.' \
  -p 'Use this transcript for context: @transcript.txt' \
  -o replies.json
```

**Shell Mode:**

```bash
# Using prompt CLI to generate replies
youtube batch-reply comments.json \
  -s 'prompt get my-prompt --content | claude --no-stream' \
  -m prompt_name=my-prompt \
  -o replies.json

# Using custom script
youtube batch-reply comments.json \
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
youtube batch-reply replies.json \
  --filter '["comment_id_1", "comment_id_2"]' \
  --rewrite \
  -p "New prompt for regeneration"

# Regenerate all replies (requires --filter to list all IDs)
youtube batch-reply replies.json \
  --filter '["all_ids_from_file"]' \
  --rewrite \
  -p "New prompt"
```

**Rewrite mode:**
- Reads existing output file
- Regenerates only the replies matching `--filter` IDs
- Updates the same file in place
- Preserves non-regenerated entries unchanged

### batch-post

Post LLM-generated replies to YouTube comments from a batch-reply output file.

```bash
youtube batch-post INPUT_FILE [OPTIONS]
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
youtube batch-post replies.json --dry-run

# Post replies with 2s delay between each
youtube batch-post replies.json --delay 2 -o posted_results.json
```

### reply

Generate reply text for YouTube comments. Use `batch-post` to actually post replies to YouTube.

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

**Output:** Generated reply objects with `comment_id` and `text` (use `batch-post` to post to YouTube)

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
youtube batch-reply comments.json \
  -p "Write a friendly, helpful reply" \
  --format json -o replies.json
youtube batch-post replies.json --dry-run              # Preview first
youtube batch-post replies.json --delay 2 -o results.json

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
│   ├── batch_reply/
│   │   └── register.py  # LLM-powered reply generation
│   ├── batch_post/
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
