# websearch

Search the web via pluggable providers. The CLI group is `websearch`; a bare
`websearch "<query>"` routes to the `search` command (see `cli/main.py`).

## Providers (plugins/)

Each provider subclasses `plugins.base.SearchPlugin` and returns a list of
`core.models.SearchItem` (fields: `url`, `title`, `description`, `source`).

| Plugin | Endpoint | Notes |
|--------|----------|-------|
| `google_news` | `news.google.com/rss/search?q=&hl=&gl=` | RSS; HTML stripped; trailing ` - Source` removed from titles |
| `reddit` | `reddit.com/search.json?q=` (global) | `--subreddit` restricts via `restrict_sr`; optional OAuth via `client_id`/`client_secret` |
| `hacker_news` | `hn.algolia.com/api/v1/search` | `--tags` (default `story`), `--points` min-score filter |

Each plugin reads its section from the tool config (`config[plugin.name]`) and
accepts an optional `transport` for testability (mirrors corpus `YouTubePlugin`).

## Commands (commands/)

- `search` — query providers; `--source` (default `all`), `--limit`, `--language`,
  `--format` (default `json`). Plugin-injected options are merged automatically
  from each `PluginManifest.cli_options["search"]`.
- `setup` — group with auto-discovered subcommands `run`, `edit`, `show`, `path`.

## Config

No common sub-config is required (`requires_common_config("websearch", [])`).
Tool config is loaded via `common.core.config.load_tool_config("websearch")`.
`websearch setup run` writes it; `language` derives `google_news.hl/gl`.

## Tests

`pytest websearch-cli/tests/` — XDG dirs are redirected to fixtures and the
profile is pinned to `test`. Network is faked via `tests/fakes.FakeTransport`.
