Improve corpus sync error handling to mark failed items and skip them on subsequent runs.

## Current Problem
When a video/note fails to sync (e.g., transcript unavailable, API error), the sync stops but the failed item is retried every time, causing repeated failures.

## Required Solution

### 1. Add Failure Tracking Table
Add to `storage/sqlite_store.py` (or SQLAlchemy models if migrated):
````sql
CREATE TABLE IF NOT EXISTS sync_failures (
    id INTEGER PRIMARY KEY,
    source_plugin TEXT NOT NULL,
    source_id TEXT NOT NULL,
    error_message TEXT NOT NULL,
    error_type TEXT NOT NULL,  -- 'transient' | 'permanent'
    failed_at TEXT NOT NULL,
    retry_count INTEGER DEFAULT 0,
    last_retry_at TEXT,
    UNIQUE(source_plugin, source_id)
);
````

### 2. Error Classification
Create `core/sync_errors.py`:
````python
class SyncError(Exception):
    """Base sync error with retry policy."""
    permanent: bool = False  # If True, never retry

class TranscriptUnavailableError(SyncError):
    permanent = True  # Don't retry transcript failures

class APIRateLimitError(SyncError):
    permanent = False  # Retry rate limits after backoff

class NetworkError(SyncError):
    permanent = False  # Retry network issues
````

### 3. Update SyncEngine Logic
Modify `core/sync_engine.py`:
````python
def sync(self, plugin: SourcePlugin, mode: str, limit: int) -> SyncResult:
    known_id_dates = self.store.get_indexed_id_dates(plugin.name) if mode == "new" else {}
    
    # NEW: Get permanently failed items to skip
    permanent_failures = self.store.get_permanent_failures(plugin.name)
    
    items = plugin.list_items(limit=limit, known_id_dates=known_id_dates)
    
    for item in items:
        # Skip permanently failed items
        if item.source_id in permanent_failures:
            logger.info("skipping_permanent_failure", 
                       source=plugin.name, 
                       source_id=item.source_id)
            continue
            
        try:
            document = plugin.fetch(item)
            # ... existing indexing logic ...
            
            # Clear any previous failures on success
            self.store.clear_failure(plugin.name, item.source_id)
            
        except SyncError as exc:
            error_type = "permanent" if exc.permanent else "transient"
            self.store.record_failure(
                plugin.name, 
                item.source_id, 
                str(exc),
                error_type
            )
            logger.error("sync_item_failed",
                        source=plugin.name,
                        source_id=item.source_id,
                        error_type=error_type,
                        error=str(exc))
            failures.append(SyncFailure(source_id=item.source_id, error=str(exc)))
        except Exception as exc:
            # Unknown errors are transient by default
            self.store.record_failure(
                plugin.name,
                item.source_id,
                str(exc),
                "transient"
            )
            # ... existing error handling ...
````

### 4. Add Store Methods
Add to `SQLiteStore`:
````python
def record_failure(self, source_plugin: str, source_id: str, 
                   error: str, error_type: str) -> None:
    """Record or update a sync failure."""
    # Upsert with retry count increment
    
def get_permanent_failures(self, source_plugin: str) -> set[str]:
    """Return source_ids of permanently failed items."""
    # SELECT source_id WHERE error_type='permanent'
    
def clear_failure(self, source_plugin: str, source_id: str) -> None:
    """Remove failure record after successful sync."""
    
def list_failures(self, source_plugin: str | None = None) -> list[dict]:
    """List all failures for debugging/admin."""
````

### 5. Add Retry Command
Create `commands/retry-failures/register.py`:
````python
@click.command("retry-failures")
@click.option("--source", type=click.Choice([...]))
@click.option("--clear-permanent", is_flag=True, 
              help="Also retry permanent failures")
def retry_failures_cmd(source, clear_permanent):
    """Retry transient failures, optionally clear permanent ones."""
    # Clear transient failures or all failures
    # Re-run sync
````

### 6. Update YouTube Plugin
Modify `plugins/youtube/plugin.py` to raise proper errors:
````python
def fetch(self, item_meta: ItemMeta) -> Document:
    try:
        transcript = self.transport.get_transcript(video_id, cookies)
    except TranscriptNotAvailable:
        raise TranscriptUnavailableError(
            f"No transcript for {video_id}"
        ) from None
    except RateLimitError:
        raise APIRateLimitError("YouTube API rate limit") from None
````

## Testing Requirements
- Test permanent failure skip behavior
- Test transient failure retry logic
- Test failure clearing on success
- Test retry-failures command

## Update Documentation
- Update `README.md` with failure handling explanation
- Update `storage/AGENTS.md` with failure tracking schema
- Add troubleshooting section

Follow GOLDEN_RULES: FAIL LOUDLY, document to avoid repeating errors, keep code minimal and explicit.
