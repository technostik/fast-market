# plugins/

## 🎯 Purpose
Provides source plugins that fetch content from external services (YouTube, RSS) and convert them into a standardized ItemMetadata format.

## 🏗️ Essential Components
- `base.py` — Plugin base classes and manifest (includes cooldown support)
- `youtube/` — YouTube RSS feed fetcher
- `rss/` — Generic RSS/Atom feed fetcher
- `yt_search/` — YouTube search keyword monitor

## 📋 Core Responsibilities
- Fetch items from external sources
- Convert to `ItemMetadata` format
- Validate identifier formats
- Provide display names for sources
- Enforce cooldown between fetches (via base class)

## 🔗 Dependencies & Integration
- Imports from: `core.models` (ItemMetadata), `core.time_scheduler` (parse_interval)
- Used by: `commands/run/register.py` (via plugin_manifests)
- External deps: `feedparser`

## ✅ Do's
- Implement `fetch_new_items()` as `async` method
- Return items in chronological order (oldest first)
- Stop iteration when `last_item_id` is reached
- Populate `extra` dict with plugin-specific metadata
- Use `feedparser` for RSS/Atom parsing
- Handle missing/invalid feed entries gracefully
- Call `super().__init__(config, source_config)` in plugin `__init__`
- Call `self._should_fetch()` at start of `fetch_new_items()`

### Base Plugin Cooldown

All plugins inherit cooldown functionality from `SourcePlugin`:

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `slowdown` | str | `"15m"` | Minimum time between fetches |
| `last_check` | datetime | `None` | Timestamp of last fetch |
| `metadata` | dict | `{}` | Source metadata from storage |

**Methods:**
- `_should_fetch()` — Returns `True` if cooldown elapsed, `False` if still cooling
- `_parse_interval(interval_str)` — Parse `"15m"` → `900` seconds

**Cooldown Logic:**
- Never fetched before (`last_check` is `None`) → Always fetch
- Enough time elapsed → Fetch
- Still in cooldown period → Skip (return empty list)

### YouTube Plugin
- Detect shorts (duration < 60 seconds)
- Content types: `short`, `medium_video` (1-10min), `video` (10-60min), `long_video` (> 1h)
- Extract duration from `media_content`
- Parse `published_parsed` with timezone
- Support channel ID, @handle, and channel URLs

### YouTube Search Plugin (yt-search)
Monitors YouTube search results for keywords instead of a specific channel.

**Identifier**: Search keywords string (e.g., `"AI tutorial machine learning"`)

**Source Metadata Options**:
| Field | Default | Description |
|-------|---------|-------------|
| `slowdown` | `"15m"` | Minimum time between searches (e.g., `"15m"`, `"1h"`, `"30m"`) |
| `min_views` | `1000` | Minimum view count to include in results |
| `max_results` | `50` | Maximum videos to fetch per search |
| `theme` | - | User-defined theme (via `--meta`) |

**Extra Fields**:
- `search_keywords` — The keywords used
- `channel_id`, `channel_name` — Video's source channel
- `duration_seconds`, `views`, `likes`, `comments`
- `is_short`, `tags`, `categories`

**Content Types**: `short`, `medium_video`, `video`, `long_video`

**Advanced Search Syntax**:
```
# Exclude shorts
"AI tutorial -shorts"

# OR operator (pipe)
"cat video | dog video"

# Exact phrase
"\"machine learning\" basics"

# Date range
"AI tutorial 2024..2026"

# Exclude specific terms
"python -beginner -tutorial"

# Combined
"\"machine learning\" tutorial -shorts | \"deep learning\""
```

**Example Setup**:
```bash
monitor setup source-add --plugin yt-search \
  --identifier "AI tutorial machine learning" \
  --meta theme=technology \
  --meta slowdown=30m \
  --meta min_views=5000 \
  --meta max_results=30
```

### RSS Plugin
- Parse categories/tags from feed entries
- Estimate word count from content/summary
- Support RSS, Atom, and feeds with `feed` in URL
- Extract author information when available

### Channel List Plugin (channel_list)
Monitor multiple YouTube channels from a single source configuration.

**Identifier**: Placeholder (not used, can be any value)

**Source Metadata Options**:
| Field | Default | Description |
|-------|---------|-------------|
| `channels` | - | List of `{id: "UC...", title: "Channel Name"}` dicts |
| `file` | - | Path to YAML channel list file (alternative to inline channels) |
| `thematic` | - | Thematic name to use from external file (required with `file`) |

**How It Works**:
- Delegates to YouTube plugin for each channel independently
- Each channel maintains its own `last_item_id` in `source.metadata.last_item_ids_by_channel`
- Results are merged and sorted by published date
- Source-level `seen_items` tracking prevents duplicates across runs

**Extra Fields Added to Items**:
- `channel_url` — YouTube channel URL (e.g., `https://www.youtube.com/channel/UCxxxx`)
- `channel_name` — Channel title from configuration
- `channel_list_title` — Same as channel_name (for backward compatibility)

**Placeholders in Actions**:
For `channel_list` sources, these placeholders are **channel-specific**:
- `$SOURCE_URL` → Channel URL (from `item.extra.channel_url`)
- `$SOURCE_DESC` → Source description + channel name (e.g., `"Tech channels (Linus Tech Tips)"`)

**Example Setup**:
```bash
# Inline channels
monitor setup source-add --plugin channel_list \
  --identifier list \
  --slowdown 15m \
  --meta 'channels=[{"id":"UCX6OQ3DkcsbYNE6H8uQQuVA","title":"MrBeast"},{"id":"UCq-Fj5jknLsUf-MWSy4_brA","title":"T-Series"}]'

# From external file
monitor setup source-add --plugin channel_list \
  --identifier list \
  --slowdown 15m \
  --meta file=/path/to/channels.yaml \
  --meta thematic=tech
```

**Example Action**:
```bash
monitor setup action-add --id notify \
  --command 'echo "New video from $SOURCE_DESC at $SOURCE_URL: $ITEM_TITLE"'
```

When triggered by MrBeast:
- `$SOURCE_URL` → `https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA`
- `$SOURCE_DESC` → `My channels (MrBeast)`

**Rule Conditions**:
```bash
# Match only channel_list sources
monitor setup rule-add --name "Channel List Videos" \
  --conditions "source_plugin == 'channel_list' and content_type == 'video'" \
  --action-ids notify

# Match specific channel by name
monitor setup rule-add --name "MrBeast Videos" \
  --conditions "source_plugin == 'channel_list' and extra.channel_name == 'MrBeast'" \
  --action-ids notify
```

**External File Format** (YAML):
```yaml
channels:
  mrbeast:
    id: UCX6OQ3DkcsbYNE6H8uQQuVA
    title: MrBeast
  tseries:
    id: UCq-Fj5jknLsUf-MWSy4_brA
    title: T-Series

thematics:
  tech:
    channels:
      - mrbeast
      - tseries
```

**Benefits**:
- Single source to manage multiple channels
- Each channel tracks its own progress independently
- Shared rules and actions across all channels
- Reduced configuration overhead for large channel lists

## ❌ Don'ts
- Don't use blocking I/O — always use async
- Don't modify the `ItemMetadata` after creation
- Don't raise exceptions for transient failures — log and return empty list
- Don't hardcode field names — use `extra` dict
- Don't assume feed has all fields — use `hasattr()` checks

## 🛠️ Extension Points

### Add New Source Plugin
1. Create `plugins/your_source/` directory
2. Subclass `SourcePlugin` in `plugin.py`
3. Implement required methods:
   - `fetch_new_items()` — async, return list of ItemMetadata
   - `validate_identifier()` — return bool
   - `get_identifier_display()` — return str
4. Create `register.py` returning `PluginManifest`
5. Update `pyproject.toml` to include new package

### Implement Plugin Validation
```python
def validate_identifier(self, identifier: str) -> bool:
    # Check format (URL, ID, etc.)
    return identifier.startswith("expected_prefix")
```

### Handle Async Fetch
```python
async def fetch_new_items(self, last_item_id=None, limit=50):
    # Fetch feed (blocking in thread if needed)
    # Convert entries to ItemMetadata
    # Stop at last_item_id
    return items
```

## 📚 Related Documentation
- See `AGENTS.md` (root) for system overview
- See `plugins/base.py` for PluginManifest
- See `plugins/youtube/plugin.py` for YouTube implementation
- See `plugins/rss/plugin.py` for RSS implementation
