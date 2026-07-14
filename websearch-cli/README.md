# websearch

Search the web through pluggable providers and get back normalized results
(`url`, `title`, `description`, `source`).

## Install

```bash
pip install -e websearch-cli
```

## Configure

```bash
websearch setup run     # interactive wizard: language, limit, reddit keys
websearch setup show    # print effective config
websearch setup edit    # open config.yaml in your editor
websearch setup path    # print config file path
```

Config lives at `~/.config/fast-market/profiles/<profile>/websearch/config.yaml`:

```yaml
language: fr            # default for google_news hl/gl
limit: 10              # items requested per provider
google_news:
  hl: fr
  gl: FR
reddit:
  user_agent: "fast-market-websearch/1.0"
  client_id: ""        # optional, raises rate-limit headroom
  client_secret: ""
hacker_news:
  tags: story
```

## Search

```bash
# Bare query searches every provider and prints JSON
websearch "fast market ai"

# Explicit subcommand
websearch search "fast market ai"

# One provider, text output, custom limit
websearch search "llm" --source reddit --limit 5 --format text

# Per-provider options
websearch search "rust" --source google_news --hl en --gl US
websearch search "python" --source reddit --subreddit programming --sort new
websearch search "startup" --source hacker_news --points 100
```

With no `--source` the command queries **all** providers and merges the results.
Default output is JSON (`--format json`); use `--format text` for a readable list.
