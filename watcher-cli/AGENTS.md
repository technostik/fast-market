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
- **Stooq**: `https://stooq.com/q/d/l/?s=<symbol>&i=d`, unauthenticated daily CSV. Used for Brent `co.f`, WTI `cl.f`, and gold `xauusd`. Stooq is an unofficial endpoint; ticker availability, licensing, and publication lag must be verified. Stooq sits behind a bot-check wall that breaks automated CSV fetches — failures surface as `ProviderError`, never silently.
- **FRED**: `https://api.stlouisfed.org/fred/series/observations`, keyed via `FRED_API_KEY` in the watcher `.env`. Generic `series_id` symbols (e.g. `DGS10`). France 10Y is monthly-only here (`IRLTLT01FRM156N`), so it is not used for the daily watchlist.
- **Banque de France Webstat**: `https://webstat.banque-france.fr/export/csv-columns/fr/catalog/<DATASET>`, keyless `;`-separated CSV with decimal commas. Used for the daily France TEC10 `FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA` (official, current-day). Full-dataset export (~1.4MB for FM); per-series export is unsupported, so the provider downloads the dataset and extracts one column. Never silently substitute another country's series.
- **CoinGecko**: public `/api/v3/simple/price` and `/api/v3/coins/<id>/market_chart`; no key is used by this MVP. Public rate limits and historical-window limits apply; rate-limit responses are typed errors.
- **DBnomics**: public `https://api.db.nomics.world/v22/series/<provider>/<dataset>/<series>?observations=1`, no authentication. It mirrors official series and can have publication lag; do not use it as a daily-market-price replacement.
- **Google News RSS**: `https://news.google.com/rss/search?q=...`; unofficial RSS search. It is isolated as `google_news`; URLs, availability, and ToS/rate limits need periodic verification.
- **Kraken**: public `https://api.kraken.com/0/public/Ticker` + `OHLC?interval=1440`; no key, ~1 req/s. Primary crypto source (same `coin:currency` symbols as CoinGecko); falls back to Coinbase spot internally.
- **Coinbase**: public `https://api.coinbase.com/v2/prices/<BASE>-<CUR>/spot` for latest, Exchange `candles?granularity=86400` for history; no key. Used as Kraken fallback.
- **Yahoo**: undocumented `https://query1.finance.yahoo.com/v8/finance/chart/<ticker>`; keyless JSON but requires a browser-like User-Agent (see `core/http.py` `headers=`) and may break without notice. Used for SPCX, `MDE10.AS` (Bund 10Y), `^IXIC`, `GC=F`, `EURUSD=X`.
- **CNBC**: keyless `quote-html-webservice/restQuote` quick quotes; used for `GB10Y` latest only (no history endpoint — history accumulates in storage). Values arrive as `"5.377%"` strings.
- **BdOR**: `https://www.bdor.fr/cours-or` HTML table; parses the `Actualisation en direct - DD/MM/YYYY` fixing date and the `prixAffiche` row for a product slug (e.g. `20-francs-napoleon-or`). Dealer page, not an API — strict parsing, failures surface as `ProviderError`. Fixings publish on business days only.

## Template conflicts
The requested `watcher.yaml` conflicts with the template's conventional tool file name `config.yaml`. Behavior requires a clearly named watchlist YAML, so it is stored beside template config at `watcher/watcher.yaml`; the template's XDG/profile paths, entry point, registry, logging and test isolation are retained. The prompt refers to `.doc/GOLDEN_RULES.md`, but that file is absent in this checkout; `_doc/BUILD_NEW_AGENT_CLI.md` was followed.

## Webux tab
`webux/watcher/register.py` contributes the **Watcher** tab to `webux serve` (entry point `watcher` in `pyproject.toml`). It shells out to the `watcher` CLI (`dashboard --json`, `history --json`) over subprocess — never import watcher `core.*`/`commands.*` in the webux process (namespace collision with webux-cli's own packages). Endpoints: `GET /api/watcher/dashboard?last=&profile=`, `GET /api/watcher/history?variable=&since=&profile=`. Partial provider errors still return HTTP 200 with per-variable `error` fields (parsed from CLI stdout despite exit 1); total CLI failure → 502, missing binary → 503.

## Do not
Do not add presentation/UI, alerting, LLM news summaries, intraday storage, or provider-specific conditionals to commands. Do not make a source failure omit a configured variable.
