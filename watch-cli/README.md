# watch

Personal terminal watchlist for market and macro observations plus RSS news.

```bash
pip install -e ./watch-cli
watch wizard
watch get
watch get --json
watch history bitcoin --since 6m
watch news --topic oil_opec --json
watch dashboard
```

Configuration is profile-scoped at `~/.config/fast-market/profiles/<profile>/watch/watch.yaml`. Run `watch setup` to edit and validate it. Secrets (if a future provider needs them) belong in adjacent `.env`, never in YAML.
