# commands/add/

Implements the `corpus add` CLI command.

Indexes one document whose content is already known — no plugin `fetch()`, no
YouTube API call, no quota. Used by the webux publish pipelines to add a
just-uploaded video (URL, title, description, transcript) to the corpus without
waiting for YouTube captions to become available.

## Behaviour

1. Reads the transcript (inline or `--transcript-file`) and description
   (inline or `--description-file`); an empty transcript is rejected.
2. Builds a `Document` whose `raw_text` is the transcript and whose metadata
   mirrors what the YouTube plugin writes (`id`, `title`, `description`,
   `published_at`, `url`, `duration_seconds`, `privacy_status`).
3. Calls `SyncEngine.add_document()`: handle, content hash, document upsert,
   chunk embeddings, pool row `synced`, failure clearing.
4. Prints `{source, source_id, handle, indexed, chunks, url}`.

`indexed` is `false` when the same transcript is already stored
(`upsert_document` short-circuits on an unchanged content hash).

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--source` | first plugin (youtube) | Source plugin the document belongs to |
| `--id` | required | Source ID (YouTube video ID) |
| `--url` | required | Public URL of the document |
| `--title` | required | Document title |
| `--transcript` / `--transcript-file` | required | Transcript content |
| `--description` / `--description-file` | empty | Description, stored in metadata only |
| `--privacy` | unknown | Privacy status |
| `--duration` | 0 | Duration in seconds |
| `--published-at` | now | ISO 8601 publish date |
| `--format`, `-F` | text | Output format: json/text |

## register.py

`register(plugin_manifests) -> CommandManifest`

Called once at startup after plugin discovery; the `--source` choices come from
the discovered plugins (never a hardcoded list).
