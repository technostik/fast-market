# commands/get-from-source/

Implements the `corpus get-from-source` CLI command.

Retrieves a document by source plugin and ID, auto-syncing if not already indexed.

## Behaviour

1. Auto-detects source from ID if not provided:
   - YouTube URLs or 11-char IDs → youtube
   - File paths (contains `/` or ends with `.md`) → obsidian
   - Single plugin available → auto-selects it
2. Checks if document exists in store by (source, source_id)
3. If found → returns document immediately
4. If not found → auto-syncs:
   - Fetches metadata/details from source
   - Fetches full document content
   - Stores document, chunks, and embeddings
   - Updates sync cursor
5. Outputs document in requested format

## Source-Specific ID Formats

### YouTube
- Video ID: `dQw4w9WgXcQ`
- Full URLs: `https://youtube.com/watch?v=XXX`, `https://youtu.be/XXX`, etc.

### Obsidian
- Vault-relative path: `notes/foo.md`, `Journal/2024-01-15.md`

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--what` | content | What to display: meta/content/all |
| `--format`, `-F` | text | Output format: json/text |

## Error Handling

Fails loudly with explicit messages:
- Could not auto-detect source (with available sources listed)
- Invalid YouTube URL/ID
- Video/note not found
- Rate limiting, network errors
- Fetch errors

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
