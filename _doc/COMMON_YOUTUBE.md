# common/youtube

Shared YouTube API library for fast-market tools.

## Overview

This module provides a clean, reusable YouTube API client with:
- **Quota tracking** - Monitor API usage against daily limits
- **Pydantic models** - Type-safe data structures
- **Error handling** - Fail-loudly with structured logging
- **Modular design** - Import only what you need

## Quick Start

```python
from common.youtube import YouTubeClient, YouTubeOAuth
from common.core.paths import get_tool_config

# Load config
client_secret = str(get_tool_config("youtube").parent / "client_secret.json")

# Authenticate
auth = YouTubeOAuth(client_secret)
api_client = auth.get_client()

# Create client
yt = YouTubeClient(api_client, channel_id="YOUR_CHANNEL_ID")

# Use it
videos = yt.search_videos("python tutorial", max_results=10)
for video in videos:
    print(f"{video.title} - {video.url}")
```

## Components

### Client (`common.youtube.client`)

Main API wrapper class.

```python
from common.youtube import YouTubeClient

yt = YouTubeClient(
    api_client,              # googleapiclient Resource
    channel_id="...",        # Optional, needed for replies
    quota_limit=10000,       # Daily quota limit
)
```

**Methods:**

| Method | Description |
|--------|-------------|
| `search_videos(query, max_results, order, language, combine_keywords)` | Search for videos |
| `get_comments(video_id, max_results, order)` | Get video comments |
| `post_comment_reply(comment_id, text)` | Reply to a comment |
| `get_channel_info(channel_id)` | Get channel details |
| `get_video_details(video_id)` | Get video statistics |
| `get_trending_videos(language, category_id, max_results)` | Get trending videos |
| `get_channel_videos(channel_id, max_results)` | Get all channel videos |
| `get_quota_usage()` | Get current quota usage |

### Models (`common.youtube.models`)

Pydantic models for all data structures.

```python
from common.youtube import Video, Comment, ReplyResult, ChannelInfo

# Video model fields:
video.video_id      # str
video.title         # str
video.description   # str
video.channel_id    # str
video.channel_title # str
video.view_count    # int
video.like_count    # int
video.comment_count # int
video.published_at  # str (ISO format)
video.url           # str

# Comment model fields:
comment.id          # str
comment.text        # str
comment.author      # str
comment.published_at # str
comment.video_id    # str
comment.like_count  # int

# ReplyResult model fields:
reply.id            # str
reply.parent_id     # str
reply.text          # str
reply.moderation_status # str
```

### Quota Tracking (`common.youtube.quota`)

Track API quota usage.

```python
from common.youtube import QuotaTracker

tracker = QuotaTracker(limit=10000)
tracker.track(100)  # Track quota usage
state = tracker.get_state()

print(f"Used: {state.usage}/{state.limit}")
print(f"Percentage: {state.usage_percentage}%")
```

### Utilities (`common.youtube.utils`)

Helper functions.

```python
from common.youtube import (
    format_count,      # format_count(1500) -> "1.5K"
    format_duration,   # format_duration(3661) -> "1:01:01"
    iso_duration_to_seconds,  # Parse "PT1H2M3S" -> 3723
    is_short_video,    # Check if duration <= 60 seconds
    timecode_to_seconds,     # Parse "01:02:03.456" -> 3723.456
    parse_srt,        # Extract text from SRT format
)
```

## Configuration

The library reads configuration from `~/.local/share/fast-market/config/youtube.yaml`:

```yaml
youtube:
  channel_id: "YOUR_CHANNEL_ID"
  quota_limit: 10000
  client_secret_path: "~/.local/share/fast-market/config/client_secret.json"
```

**Config locations:**
- Config: `~/.local/share/fast-market/config/youtube.yaml`
- Client secret: `~/.local/share/fast-market/config/client_secret.json`
- OAuth token: `~/.local/share/fast-market/config/token.json`

## Error Handling

The client raises exceptions on API errors:

```python
from googleapiclient.errors import HttpError

try:
    videos = yt.search_videos("test")
except HttpError as e:
    print(f"API error: {e}")
except ValueError as e:
    print(f"Config error: {e}")
```

## Logging

Uses structlog for structured logging:

```python
from common import structlog

logger = structlog.get_logger(__name__)
logger.info("video_found", video_id="abc123", title="Test")
```

## YouTube API Quotas

Default daily quota is 10,000 units. Key operations:

| Operation | Quota Cost |
|-----------|-----------|
| `search_videos()` | 100 units |
| `get_comments()` | 1 unit |
| `post_comment_reply()` | 50 units |
| `get_channel_info()` | 1 unit |
| `get_video_details()` | 1 unit |

## Integrating with a CLI Tool

See `youtube-agent/` for a complete example.

```python
# core/engine.py
from common.youtube.auth import YouTubeOAuth
from common.youtube import YouTubeClient
from common.core.config import load_tool_config

def build_client() -> YouTubeClient:
    config = load_tool_config("youtube")
    auth = YouTubeOAuth(config["youtube"]["client_secret_path"])
    return YouTubeClient(auth.get_client(), channel_id=config["youtube"]["channel_id"])
```

## Dependencies

```
google-api-python-client>=2.0
google-auth-oauthlib>=1.0
google-auth>=2.0
pydantic>=2.0
structlog>=24.0
```

## File Structure

```
common/youtube/
├── __init__.py    # Main exports
├── auth.py        # Re-exports YouTubeOAuth
├── client.py      # YouTubeClient class
├── models.py      # Pydantic models
├── quota.py       # QuotaTracker
└── utils.py       # Helper functions
```
