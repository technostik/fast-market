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

### reply

Post replies to YouTube comments.

```bash
youtube reply [COMMENT_ID] [TEXT] [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--from-file` | JSON/YAML file with array of {comment_id, text} |
| `-f, --format` | Output: json, yaml, text |
| `-o, --output` | Save results to file |
| `--stdin` | Read from stdin (JSON array) |

**Examples:**
```bash
# Single reply
youtube reply COMMENT_ID "Thanks for watching!"

# Batch replies from file
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

## Features

### Quota Tracking
- Automatically tracks YouTube API quota usage
- Default limit: 10,000 units/day (YouTube Data API standard)
- Quota persists across sessions in `~/.cache/fast-market/youtube/quota.json`
- Prevents accidental quota exhaustion

### Piping Support
All commands support JSON/YAML streaming for pipeline composition:

```bash
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
│   ├── search/
│   │   └── register.py  # Search implementation
│   ├── comments/
│   │   └── register.py  # Comments implementation
│   ├── reply/
│   │   └── register.py  # Reply implementation
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
