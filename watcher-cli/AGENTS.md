# watcher

## Purpose
`watcher` is a profile-scoped personal market/macro watchlist. Keep provider adapters generic by source: a variable is configuration (`provider` + opaque `symbol`), never a provider module. Core services return typed data and do not render output; commands render compact text or stable JSON.

## Architecture
- Auto-discovered provider `register.py` files live in `plugins/*/`; auto-discovered command `register.py` files live in `commands/*/`.
- Config is `~/.config/fast-market/profiles/<profile>/watcher/watcher.yaml`; secrets only belong in the adjacent `.env`; data is `~/.local/share/fast-market/profiles/<profile>/watcher/watcher.sqlite3`.
- Add catalog entries only in `catalog.yaml`. Adding a variable that uses an existing provider must require no Python changes.
- Never log secrets. Preserve an observation's actual as-of date; never label a stale or low-frequency series as current.

## Source findings (checked 2026-10-01)
Network egress in the build environment was blocked by the proxy (`CONNECT tunnel failed, 403`), so live endpoints could not be verified here. Implementations are isolated and must be rechecked before relying on them in production:
- **Stooq**: `https://stooq.com/q/d/l/?s=<symbol>&i=d`, unauthenticated daily CSV. Used for Brent `co.f`, WTI `cl.f`, gold `xauusd`, and the indicative France 10Y candidate `10yfr`. Stooq is an unofficial endpoint; ticker availability, licensing, and publication lag must be verified. The OAT ticker is particularly fragile and can fail loudly rather than silently substituting data.
- **CoinGecko**: public `/api/v3/simple/price` and `/api/v3/coins/<id>/market_chart`; no key is used by this MVP. Public rate limits and historical-window limits apply; rate-limit responses are typed errors.
- **DBnomics**: public `https://api.db.nomics.world/v22/series/<provider>/<dataset>/<series>?observations=1`, no authentication. It mirrors official series and can have publication lag; do not use it as a daily-market-price replacement.
- **Google News RSS**: `https://news.google.com/rss/search?q=...`; unofficial RSS search. It is isolated as `google_news`; URLs, availability, and ToS/rate limits need periodic verification.

## Template conflicts
The requested `watcher.yaml` conflicts with the template's conventional tool file name `config.yaml`. Behavior requires a clearly named watchlist YAML, so it is stored beside template config at `watcher/watcher.yaml`; the template's XDG/profile paths, entry point, registry, logging and test isolation are retained. The prompt refers to `.doc/GOLDEN_RULES.md`, but that file is absent in this checkout; `_doc/BUILD_NEW_AGENT_CLI.md` was followed.

## Do not
Do not add presentation/UI, alerting, LLM news summaries, intraday storage, or provider-specific conditionals to commands. Do not make a source failure omit a configured variable.
