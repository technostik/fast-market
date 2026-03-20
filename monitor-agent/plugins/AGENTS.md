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
| `check_interval` | str | `"15m"` | Minimum time between fetches |
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
- Extract duration from `media_content`
- Parse `published_parsed` with timezone
- Support channel ID, @handle, and channel URLs

### YouTube Search Plugin (yt-search)
Monitors YouTube search results for keywords instead of a specific channel.

**Identifier**: Search keywords string (e.g., `"AI tutorial machine learning"`)

**Source Metadata Options**:
| Field | Default | Description |
|-------|---------|-------------|
| `check_interval` | `"15m"` | Minimum time between searches (e.g., `"15m"`, `"1h"`, `"30m"`) |
| `min_views` | `1000` | Minimum view count to include in results |
| `max_results` | `50` | Maximum videos to fetch per search |
| `theme` | - | User-defined theme (via `--meta`) |

**Extra Fields**:
- `search_keywords` — The keywords used
- `channel_id`, `channel_name` — Video's source channel
- `duration_seconds`, `views`, `likes`, `comments`
- `is_short`, `tags`, `categories`

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
  --meta check_interval=30m \
  --meta min_views=5000 \
  --meta max_results=30
```

### RSS Plugin
- Parse categories/tags from feed entries
- Estimate word count from content/summary
- Support RSS, Atom, and feeds with `feed` in URL
- Extract author information when available

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
