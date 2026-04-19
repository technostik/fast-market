# commands/diagnose/

## 🎯 Purpose
Diagnose command that checks if all videos published on the current day from monitored sources have been processed by the monitor run. It fetches recent videos, filters to today's publications, and verifies each appears in the trigger logs.

## 📋 Command Options

### --cron
Run in cron mode (minimal output).

### --limit
Max items to fetch per source (default: 100).

### --format
Output format: `json`, `yaml`, or `text`.

## Execution Flow

1. Load all enabled sources
2. For each source, fetch items published on the current day only (force mode, date_filter='today' to minimize API calls and yt-dlp usage)
3. For each fetched video (already filtered to today), check trigger_logs to determine status:
   - `triggered`: logged with exit_code=0 and rule_id != "ignored"
   - `error`: logged with exit_code != 0
   - `ignored`: logged with rule_id="ignored"
   - `unfound`: not logged at all
4. Output all today videos with their status, plus summary of missing ones

## Output Format

```json
{
  "total_fetched": 250,
  "total_today": 15,
  "total_logged": 12,
  "total_missing": 3,
  "missing_videos": [
    {
      "item_id": "vid123",
      "title": "Video Title",
      "url": "https://...",
      "published": "2024-01-15T10:00:00+00:00",
      "source_id": "source-uuid",
      "source_plugin": "youtube"
    }
  ],
  "errors": []
}
```

## 🔗 Dependencies
- Imports from: `commands.base`, `commands.helpers`, `core.models`, `core.storage`
- Uses plugins for fetching items

## ✅ Do's
- Fetch in force mode to get comprehensive recent data
- Handle fetch errors gracefully per source
- Use timezone-aware date filtering
- Check for minimum fetch count (warn if <10 total)

## ❌ Don'ts
- Don't update source tracking (diagnostic only)
- Don't execute actions or log triggers
- Don't fail on individual source errors