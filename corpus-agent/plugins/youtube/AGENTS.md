# plugins/youtube

- Keep code minimal and explicit.
- Use structlog, raise explicit exceptions.

## Sync cursor: ID-based, NOT date-based

`list_items` receives `known_ids` (set of already-indexed source_ids) from SyncEngine.
It walks the uploads playlist newest-first, skipping known IDs, until it has `limit`
new eligible videos or exhausts the channel.

DO NOT use a date cursor (`since`) for YouTube. The playlist API returns videos
newest-first; after the first sync, every backlog video has published_at older than
the newest indexed one — a date filter would silently skip the entire backlog.
The `since` parameter is accepted for interface compatibility but intentionally ignored.

## Transport abstraction

`YouTubeTransport` implements three methods used by `list_items`:
- `get_uploads_playlist(channel_id)` — resolve channel → playlist ID (called once)
- `iter_playlist_pages(playlist_id)` — yield pages of 50 playlist snippet dicts
- `get_video_details(video_ids)` — enrich a page with duration/description/privacy

Tests inject a fake `Transport` to avoid real API calls.

## Privacy status

`privacyStatus` is fetched via the `status` part of `videos.list`.
Default: non-public videos (private, unlisted) are skipped at list_items time.
Override with `youtube.index_non_public: true` in config.yaml.
`privacy_status` is stored on every Document and exposed in search results.

## register.py

`register(config) -> PluginManifest` declares what this plugin contributes
to the CLI, API, and frontend. Current contributions:

- `cli_options["search"]`: --type, --min-duration, --max-duration, --privacy-status
- No plugin-specific API routes
- No frontend JS fragment

To add a new CLI option to a command, add a click.Option to the relevant
cli_options list. The registry injects it automatically. Do not touch main.py.

## Note on --source option

The --source CLI option (choosing which plugin to target) is built by COMMANDS
from plugin_manifests.keys(). This plugin must NOT declare --source.
