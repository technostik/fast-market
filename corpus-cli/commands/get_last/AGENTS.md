# commands/get-last/

Implements the `corpus get-last` CLI command.

Syncs content from sources and retrieves the most recently indexed documents.

## Behaviour

1. Runs a sync with the specified `--limit` (default: 1) to fetch new content
2. Queries the store for the most recent documents by `updated_at` date
3. Outputs the documents in the requested format

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--limit`, `-l` | 1 | Number of recent items to retrieve |
| `--source` | None | Filter by source plugin |
| `--what` | content | What to display: meta/content/all |
| `--format`, `-F` | text | Output format: json/text |

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
