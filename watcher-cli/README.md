# watcher

Personal terminal watchlist for market and macro observations plus RSS news.

```bash
pip install -e ./watcher-cli
watcher wizard
watcher get
watcher get --json
watcher history bitcoin --since 6m
watcher news --topic oil_opec --json
watcher dashboard
```

Configuration is profile-scoped at `~/.config/fast-market/profiles/<profile>/watcher/watcher.yaml`. Run `watcher setup` to edit and validate it. Secrets (if a future provider needs them) belong in adjacent `.env`, never in YAML.
