# TODO

## browser-cli (NEW — done ✅)
- [x] `start` — Launch Chromium with CDP in background (configurable browser binary, port, extra args)
- [x] `stop` — Stop the Chromium browser on the given CDP port
- [x] `run` — Run a single `agent-browser` instruction with `-P KEY=VALUE` parameter substitution
- [x] `script` — Run multiple instructions from string, `--file`, or `--stdin` with `--keep-browser` option
- [x] Parameter substitution: `{key}` placeholders replaced by `-P key=value` values
- [x] Script auto-launches browser if none detected, stops when done (unless `--keep-browser`)
