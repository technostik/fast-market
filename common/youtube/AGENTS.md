# common/youtube

## 🎯 Purpose
Shared YouTube API client, data models, OAuth authentication, and transport layer for all fast-market tools that interact with YouTube (youtube-cli, corpus-cli, webux plugins).

## 🏗️ Essential Components

```
common/youtube/
├── auth.py         # YouTubeOAuth — OAuth2 flow, token management, headless fallback
├── client.py       # YouTubeClient — API calls with quota tracking and scope retry
├── models.py       # Pydantic models: Video, Comment, ReplyResult, CommentResult, ChannelInfo, QuotaUsage
├── quota.py        # QuotaTracker, QuotaState — in-memory quota accounting
├── transport.py    # Transport ABC + RSSPlaylistTransport — RSS feed + yt-dlp fallback
├── utils.py        # format_count(), iso_duration_to_seconds(), is_short_video(), extract_video_id(), parse_srt()
├── channel_list.py # ChannelEntry, ChannelList — YAML-backed list of tracked channels
└── diagnose.py     # Auth/quota diagnostic helpers
```

## 📋 Core Responsibilities
- Authenticate with YouTube Data API v3 via OAuth2 (browser or headless)
- Execute API calls (search, comments, video details, channel info, uploads playlist) with quota tracking
- Retry on `insufficientPermissions` by refreshing auth scopes automatically
- Raise `click.ClickException` on quota exceeded so the CLI exits cleanly
- Provide transcripts via yt-dlp → youtube-transcript-api → API v3 fallback chain

## 🔗 Dependencies & Integration
- Imports from: `common.auth.base`, `common.core.paths`, `common.structlog`, `common.core.yaml_utils`
- `transport.py` also imports `core.sync_errors.TranscriptUnavailableError`, `VideoBlockedError` — this is a corpus-cli dependency; only used in corpus-specific workflows
- Used by: `youtube-cli`, `corpus-cli`, `webux` plugins
- External deps: `google-api-python-client`, `google-auth-oauthlib`, `feedparser`, `yt-dlp`, `pydantic`

## OAuth & Tokens
- Token stored at: `~/.config/fast-market/common/youtube/token.json`
- Client secret at: `~/.config/fast-market/common/youtube/client_secret.json`
- Headless fallback: when no browser is available, `YouTubeOAuth` sends a `message alert` with the OAuth URL and polls for the token file for up to 5 minutes

## API Quota
| Operation | Quota Cost |
|---|---|
| `channels.list`, `videos.list`, `playlistItems.list` | 1 unit |
| `commentThreads.list` | 1 unit |
| `comments.insert`, `commentThreads.insert` | 50 units |
| `search.list` | 100 units |

Default daily quota: 10 000 units. Configured in `~/.config/fast-market/common/youtube/config.yaml`.

## ✅ Do's
- Use `YouTubeClient` for all API calls — it tracks quota and auto-retries on scope errors
- Use `models.Video.from_search_result()` / `from_video_list()` to parse API responses
- Use `utils.extract_video_id()` to normalize YouTube URLs before passing to the client
- Use `RSSPlaylistTransport` for lightweight channel listing (no quota cost)

## ❌ Don'ts
- Do not call the YouTube API directly — always go through `YouTubeClient`
- Do not hardcode the token path — use `get_youtube_auth_dir()` from `auth.py`
- Do not call `search.list` in a tight loop — it costs 100 quota units per call

## ⚠️ Pitfalls
- `get_all_owned_videos()` returns public, private, and unlisted videos but **not** members-only videos — YouTube API limitation. For known member video IDs, use `get_videos_by_ids()` instead.
- `is_short_video()` in `utils.py` uses a threshold of ≤60 seconds (ISO 8601 duration string). `is_short_video()` in `last_video.py` uses 180 seconds. They are not the same function — check which module you're importing from.
- `transport.py` imports `core.sync_errors` from corpus-cli. If corpus-cli is not installed, importing `RSSPlaylistTransport.get_transcript()` will fail. Only `iter_playlist_pages()` and `get_video_details()` are safe to use standalone.
- Token expiry: tokens refresh automatically via `google.auth.transport.requests.Request`. If the stored token has insufficient scopes, `YouTubeClient._refresh_auth_and_rebuild()` deletes it and re-authenticates.

## 🧪 Tests
- Test files: `tests/` (project root), `youtube-cli/tests/`
- Run with: `pytest tests/`

## 🔍 Observability
- Key log markers: `auto_refreshing_auth`, `auth_refreshed_and_client_rebuilt`, `quota_tracked`, `comments_retrieved`, `search_completed`, `rss_parse_error`
- Verbose quota state: `client.get_quota_usage()` returns current usage and percentage

## 🛠️ Extension Points
- To add a new API method: add it to `YouTubeClient` in `client.py` and update quota costs
- To add a new transport backend (e.g., YouTube Data API v3 playlist): subclass `Transport` in `transport.py`

## 📚 Related Documentation
- See `README.md` for usage and CLI reference
- See `common/core/AGENTS.md` for `get_youtube_config_path()` and config loading
- See `_doc/adr/007-shared-youtube-config.md` for the shared config architecture decision
- See `youtube-cli/AGENTS.md` for youtube-cli-specific commands
