# plugins/

## 🎯 Purpose
Provides source plugins that fetch content from external services (YouTube, RSS) and convert them into a standardized ItemMetadata format.

## 🏗️ Essential Components
- `base.py` — Plugin base classes and manifest
- `youtube/` — YouTube RSS feed fetcher
- `rss/` — Generic RSS/Atom feed fetcher

## 📋 Core Responsibilities
- Fetch items from external sources
- Convert to `ItemMetadata` format
- Validate identifier formats
- Provide display names for sources

## 🔗 Dependencies & Integration
- Imports from: `core.models` (ItemMetadata)
- Used by: `commands/run/register.py` (via plugin_manifests)
- External deps: `feedparser`

## ✅ Do's
- Implement `fetch_new_items()` as `async` method
- Return items in chronological order (oldest first)
- Stop iteration when `last_item_id` is reached
- Populate `extra` dict with plugin-specific metadata
- Use `feedparser` for RSS/Atom parsing
- Handle missing/invalid feed entries gracefully

### YouTube Plugin
- Detect shorts (duration < 60 seconds)
- Extract duration from `media_content`
- Parse `published_parsed` with timezone
- Support channel ID, @handle, and channel URLs

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
