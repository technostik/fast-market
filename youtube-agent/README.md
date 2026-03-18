# youtube-agent

YouTube CLI tool for search, comments, and replies.

## Installation

```bash
cd youtube-agent
pip install -e .
```

## Configuration

Create `~/.local/share/fast-market/config/youtube-agent.yaml`:

```yaml
youtube:
  client_secret_path: "~/.local/share/fast-market/config/client_secret.json"
  channel_id: "YOUR_CHANNEL_ID"  # Required for reply command
  quota_limit: 10000
```

### Getting Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project or select existing one
3. Enable YouTube Data API v3
4. Go to Credentials → Create Credentials → OAuth client ID
5. Download the JSON file and save as `client_secret.json`

## Usage

### Search Videos

```bash
youtube search "python tutorial" --max-results 5
youtube search "python tutorial" --order date --language fr
youtube search "python" --combine  # OR search
youtube search "python" --format json -o results.json
```

### Get Comments

```bash
youtube comments dQw4w9WgXcQ --max-results 10
youtube comments dQw4w9WgXcQ --order time
youtube search "tutorial" | youtube comments --stdin --format yaml
```

### Reply to Comments

```bash
youtube reply COMMENT_ID "Your reply text"
youtube reply --from-file replies.json
cat replies.json | youtube reply --stdin
```

### Piping Examples

```bash
# Search and get comments in pipeline
youtube search "python" -n 5 --format json | youtube comments -n 3 --stdin > comments.yaml

# Chain multiple operations
youtube search "tutorial" | youtube comments --stdin | youtube reply --stdin
```

## Commands

### search
Search for YouTube videos by keywords.

Options:
- `KEYWORDS...` - Search terms
- `--max-results, -n` - Number of results (default: 10)
- `--order` - Sort by: date, relevance, rating, title, viewCount
- `--language` - Language code (default: en)
- `--combine` - Use OR instead of AND for keywords
- `--format` - Output: json, yaml, text (default: text)
- `--output, -o` - Save to file
- `--stdin` - Read video IDs from stdin for filtering

### comments
Get comments for a video.

Options:
- `VIDEO_ID` - Video ID (optional with --stdin)
- `--max-results, -n` - Number of comments (default: 20)
- `--order` - Sort by: relevance, time
- `--format` - Output: json, yaml, text (default: text)
- `--output, -o` - Save to file
- `--stdin` - Read video IDs from stdin
- `--field` - Field name to extract from stdin data (default: video_id)

### reply
Post replies to comments.

Options:
- `COMMENT_ID` - Comment ID (optional with --from-file or --stdin)
- `TEXT` - Reply text (optional with --from-file or --stdin)
- `--from-file` - JSON/YAML file with {comment_id, text} pairs
- `--format` - Output: json, yaml, text (default: text)
- `--output, -o` - Save results to file
- `--stdin` - Read from stdin (JSON array)

## Quota Tracking

The tool tracks YouTube API quota usage. The default limit is 10,000 units per day.

## Architecture

```
youtube-agent/
├── youtube_entry/       # CLI entry point
├── cli/                 # Click main group
├── core/                # Config and engine
├── commands/            # CLI commands
│   ├── search/
│   ├── comments/
│   └── reply/
└── common -> ../common   # Shared utilities symlink
```

Shared code lives in `common/youtube/`:
- `client.py` - YouTube API wrapper
- `models.py` - Pydantic models
- `quota.py` - Quota tracking
- `utils.py` - Helper functions
