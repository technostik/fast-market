# webux-cli

## 🎯 Purpose
Modular web UI server for fast-market: a single `webux serve` process hosts multiple plugin tabs, each contributing one FastAPI router and one UI page.

## 🏗️ Essential Components
- `webux_entry/__init__.py` — package entry point, exports `main`
- `cli/main.py` — CLI bootstrap: discovers plugins and commands via `common.core.registry`
- `core/server.py` — FastAPI app factory: lazy-mounts plugin routers, injects shared nav into every plugin page
- `core/security.py` — `_assert_path_safe(path, roots)` path containment guard (HTTP 403 on violation)
- `commands/serve/register.py` — `webux serve` (uvicorn, --host, --port, --open, --restart)
- `commands/setup/register.py` — `webux setup show | reset | show-path`
- `webux/fileviewer/` — **Files** tab: browse/edit config, data, workdir files with CodeMirror
- `webux/yt_poster/` — **YT Poster** tab: batch-post YouTube comments/videos, regenerate replies
- `webux/skill_runner/` — **Plan Editor** tab: load `*.run.yaml` plans, edit skill/prompt files

## 📋 Core Responsibilities
- Serve a unified dark-themed web UI at `http://host:port/`
- Mount each plugin's FastAPI router under `/api/{plugin_name}/`
- Serve each plugin's page at `/{plugin_name}` with shared nav injected automatically
- Lazy-mount routers: defer `app.include_router()` until the first request to `/{name}` or `/api/{name}/...`
- Expose `POST /api/system/exit` for in-browser server shutdown

## 🔗 Dependencies & Integration
- Imports from: `common.webux.base` (`WebuxPluginManifest`), `common.webux.registry` (`discover_webux_plugins`), `common.core.registry`, `common.core.config`, `common.structlog`
- Plugins registered via `pyproject.toml` entry group `fast_market.webux_plugins`
- `yt_poster` calls `youtube batch-comment-post/batch-video-post` and `prompt batch-apply` via subprocess
- `yt_poster` calls `toolsetup workdir prev/last` for workdir navigation
- External deps: `fastapi`, `uvicorn`, `psutil` (port kill on `--restart`), `pyyaml`, `requests` (skill_runner URL load)

## 📦 WebuxPluginManifest Contract
Each `register(config: dict) -> WebuxPluginManifest` must provide:

| Field | Description |
|-------|-------------|
| `name` | Unique slug — tab id, URL path, API prefix |
| `tab_label` | Visible tab label |
| `tab_icon` | Emoji shown in nav |
| `api_router` | `APIRouter` mounted at `/api/{name}/` |
| `frontend_html` | Full HTML page (server injects nav CSS + JS + `<nav>` automatically) |
| `order` | Integer for tab ordering (lower = leftmost) |
| `lazy` | `True` by default — defers router mount to first request |
| `group` | Toolbar dropdown group (e.g. `"Publish"`); empty = hub fallback mapping, then `"More"` |
| `busy_check` | Optional `Callable[[], bool]` — True while a long operation runs. Aggregated by `GET /api/system/busy`; the hub disables the profile switcher while any plugin is busy. Must be cheap and side-effect free (never call a status helper that auto-starts work). |

Tabs are bucketed into toolbar dropdowns (Workspace 📁, Publish 📤, Create 🎨,
Observe 👁, More 🧩) in `core/server.py` (`_WEBUX_GROUP_ORDER`,
`_WEBUX_GROUP_ICONS`, `_WEBUX_GROUP_FALLBACK`). The manifest `group` wins;
`_WEBUX_GROUP_FALLBACK` covers pre-group plugins; unknown plugins land in
"More". Custom group names render after the built-ins with a 🧩 icon.

## 🌐 API Conventions
- Plugin APIs: `/api/{plugin_name}/...`
- Plugin UI pages: `/{plugin_name}`
- Root `/` redirects to first discovered plugin tab
- `/shell` fallback page lists all tabs
- `POST /api/system/exit` → graceful shutdown
- `GET /api/system/busy` → `{"busy": bool, "active": [plugin, ...]}` aggregating every manifest's `busy_check`

## 🔒 Security Rules
- Every filesystem endpoint must call `_assert_path_safe(resolved_path, roots)` before read/write
- Use `Path.resolve()` before the safety check — never pass raw user input
- Reject out-of-root paths with HTTP 403
- Never traverse symlinks in directory trees (`_tree()` skips symlinks)

## ✅ Do's
- Discover plugins via entry points — never hardcode names in `core/server.py`
- Keep `register()` side-effect-free; defer heavy imports into request handlers
- Use `common.structlog` for all logging (structured, grep-friendly)
- Always create a `.bak` backup before overwriting files (both fileviewer and skill_runner do this)
- Fail loudly on malformed plugin registration — do not swallow errors at startup

## ❌ Don'ts
- Don't hardcode plugin names in `core/server.py`
- Don't bypass `_assert_path_safe` for any path-bearing endpoint
- Don't duplicate nav markup in plugin HTML — server injects it
- Don't mount plugin routers outside `/api/{name}/...`

## ⚠️ Pitfalls
- **--restart requires psutil**: `psutil` kills the process on the target port; if not installed the flag silently does nothing. Ensure `psutil` is in the dependencies.
- **lazy mount race**: the ASGI middleware mounts lazily; concurrent requests to an unmounted plugin may 404 on the first hit. Acceptable for single-user CLI use.
- **yt_poster subprocess path**: calls `youtube` and `prompt` CLIs — they must be in `PATH` and configured. Missing CLI → HTTP 500 with the subprocess error in the response.
- **workdir not configured**: `yt_poster` and `fileviewer` return HTTP 404 when `workdir` is absent from `~/.config/fast-market/common/config.yaml`. Run `toolsetup workdir init <path>` first.
- **plugin order**: `order` in `WebuxPluginManifest` controls tab position; lower numbers appear leftmost. Default ordering: fileviewer=30, skill_runner=20, yt_poster=40, monitor=20.
- **profile switching is locked while anything runs**: the toolbar script polls `/api/system/busy` every 3s and disables `#webux-profile` (and every `[data-profile-lock]` page picker). It re-checks once more on `change` before writing `localStorage`/reloading, so a stale poll cannot let a switch through. `busy_check` probes must be side-effect free — e.g. short_publish reads `pool._pool_state["running"]`, never `get_pool_state()` (which auto-starts the worker).
- **profile colours are deterministic, not stored**: every profile gets a dark tone from `common/webux/theme.py:profile_tones()`. Hues are **evenly spaced over the sorted profile list** (`PROFILE_HUE_OFFSET`, 2 profiles ≈ 180° apart, 3 ≈ 120°…) — a per-name hash gave two profiles near-identical blues. To force a colour, add `profile_colors: {<name>: '#rrggbb'}` to the webux tool config; the CLI writes it to the `_shared` profile so the map applies whatever the active profile is: `webux setup profile-color set <profile> '#7c3aed'` (also `show` / `clear` / `tone`). The hub emits `[data-profile="<name>"]` rules and a `window.WEBUX_PROFILE_TONES` map on each page; `.webux-nav` uses `var(--profile-bg)`, and long_publish/short_publish tint `.wrap.profile-surface` via `window.webuxApplyProfileTone(el, name)`. Short_publish pool rows call it per item with `item.profile` (fallback: page profile) so each queued channel keeps its own tone. Publish component tint is scoped to the element: the page `#jobProfile` never overwrites the toolbar's `data-profile`.
- **page profile pickers beat the toolbar**: `short_publish` and `long_publish` each have a `#jobProfile` selector defaulting to `currentProfile()` (toolbar). It drives every profile-scoped call on the page: config GET/POST, `/list-prompts?profile=`, `/list-videos?profile=` (short_publish), start/add-to-pool. Resume/Retry ignore it and use the profile persisted in the meta log so a half-processed video never moves account.
- **short_publish page picker stays usable during a pool run**: `#jobProfile` carries `data-profile-lock data-profile-lock-allow="short_publish"`, so `applyBusy()` computes `blockers = active − allow` and leaves it editable while *short_publish itself* is the busy plugin — the pool queue is sequential, so the next video can be queued for another channel while the current one uploads. It locks again as soon as another plugin is busy (two pipelines would race on the process-wide `FASTMARKET_PROFILE`). The toolbar `#webux-profile` has no allow attribute and always locks; `long_publish`'s picker stays locked too (no queue, `/start` has no guard). `data-profile-lock-allow` never goes on the toolbar select: it is matched by id, not by `data-profile-lock`.
- **short_publish pool duration is the processed file**: the pool row must show the renamed/concatenated clip (`upload_duration_seconds`, measured after step 3) — never the source-file length (`duration_seconds`). Source length belongs on the file picker only.
- **short_publish pool rows keep their add-time profile**: the YouTube account is chosen when "Add to pool" is clicked and stored on the pool item (and in the meta log). `get_pool_state()` must expose `profile` for every item so the pool's "Edit in Studio" link can show it on hover; old entries fall back to the meta log, then the active profile.
- **short_publish re-upload reuses steps 0-3**: `POST /reupload` starts at step 4 with a *target* profile and the meta's `files.final_video`, title, description and transcript. It resets `pinned_comment_id` (otherwise the target channel would never get a comment), re-applies the target profile's description signature (from `description_raw`; legacy metas strip the old profile's signature suffix), appends every publish to `uploads[]`, and updates the matching pool row via `set_item_upload_result`. The old upload is never deleted (no YouTube delete CLI) — the dialog links to Studio for manual cleanup. `_run_pipeline_core` only requires the original source for `from_step < 4`, so re-upload survives an archived source; `Clear finished` moves the final video and deletes the meta, making re-upload impossible afterwards.
- **long_publish video extensions are shared**: `youtube.publish.video_extensions` is the same key short_publish reads. The long-publish default is `mp4,mkv,webm`. A stored value that is exactly the legacy `mp4,mkv` (any order or spacing) is rewritten to that default on `GET /config`. Any other saved list, including one that drops `webm` on purpose, is left unchanged.
- **long_publish Retry uses the meta log**: `*-long-meta.json` records `completed_steps`. Retry starts at the first index missing from `completed_steps` and `skipped_steps`. The thumbnail engine select on that run overrides `youtube.publish.thumbnail_engine`; an empty select still follows the image CLI default (`flux2cloud` on this profile).
- **long_publish hides a source only once uploaded**: the video list skips a source when every step is done-or-skipped AND the upload step completed. A run that skipped the tail (no thumbnail/signature/upload) stays selectable with retry available.
- **long_publish rhythm mode is opt-in and local-only**: `rhythm_silence` (frontend "Silences" select → "🎵 Rhythm") inverts steps 0/1 — word-level JSON transcript first, then `video remove-silence --use-transcript`, then normalize of the cut. The select has 3 states (remove/rhythm/keep, default remove); the API still receives the `do_remove_silence`/`rhythm_silence` booleans. Old order untouched when off, rejected with HTTP 400 together with `use_modal`/`transcript_mode: none`/disabled silence removal, and recorded in the meta log. Step indices never change; only the per-job display names do.
- **long_publish manual mode (forced title)**: a non-empty `title_override` on `/start` or `/resume` (UI field "Title") turns the run manual — step 1 (Whisper) and the thumbnail step are skipped, and step 2 calls no LLM at all: the title is the field and the description is `description_prefix` + sources + `description_override` + signature. A non-empty `description_override` alone only replaces the summary LLM call. Overrides are persisted in `*-long-meta.json` and reused by Retry/Resume, the title is validated against YouTube's 100-char limit (HTTP 400), rhythm mode is rejected together with it (step 1 would be needed for the cut), and the frontend unchecks/disables the thumbnail controls plus the 🎵 Rhythm option while the field is non-empty. Thumbnails for such a run are built in the YT Thumbnail tab.
- **long_publish rhythm tuning lives in the publish config**: `rhythm_*` keys (tolerance, paragraph threshold, 4 pause targets, crossfade) are edited in the Config panel and passed as CLI flags to the rhythm cut. Empty = unset → the video config file / code default applies. `cut_time` (per-run, `MM:SS` or seconds, same as short_publish) trims the tail via `video cut` before anything else; it is one-time (cleared after use) and `*_cut.mp4` files are hidden from the source list like other intermediates.
- **publish → corpus is best effort and lives in one helper**: the "Add to corpus" checkbox (`#doAddCorpus` long, `#addToCorpus` short) is checked by default; it also exists on short "Add to pool" but **not** in the re-upload dialog, which inherits `do_add_to_corpus` from the meta log. Both pipelines call `webux/video_corpus.py:maybe_add_to_corpus` right after a successful upload when `do_add_to_corpus` is on, the upload was not skipped, a `video_id` exists and the video was not already indexed (`corpus_video_id`). It runs `corpus add --source youtube ...` directly (no YouTube API, no quota) and writes the description to corpus metadata only — it is not searchable. No transcript / placeholder (`(transcript unavailable)`, `(no transcript…`) / empty title → skip and append a `⚠ Corpus add failed (non-blocking)` warning to the upload step. Any corpus failure, timeout (900s) or missing `corpus` binary must stay warn-only: never let it fail the publish. The result is appended to the upload step output and indexed via `corpus_video_id`/`corpus_handle` in `*-meta.json` for resume/retry idempotency; there is deliberately **no new `STEP_NAMES` entry** (it would shift resume/retry indices).

## 🧪 Tests
- Test files: `tests/`
- Run with: `pytest tests/ -v` from `webux-cli/`
- Key scenarios: `test_fileviewer_listing.py` (tree/file API), `test_server_lazy.py` (lazy mount), `test_yt_poster.py` (post/load API)

## 🔍 Observability
- Verbose logging: pass `--verbose` via CLI context; default level is `CRITICAL`
- Key log markers: `server_start`, `server_exit_requested`, `webux_plugin_lazy_mounted`, `webux_no_matching_plugin`, `yt_poster_load`, `yt_poster_post_start`, `yt_poster_post_done`, `fileviewer_tree`, `fileviewer_read_file`, `fileviewer_save_file`, `skill_runner_tree`, `skill_runner_read_file`

## 🛠️ Extension Points
- **Add a new tab plugin**:
  1. Create `webux/<name>/` with `__init__.py`, `plugin.py` (FastAPI `APIRouter`), `register.py` (returns `WebuxPluginManifest`)
  2. Add entry point in `pyproject.toml` under `[project.entry-points."fast_market.webux_plugins"]`
  3. Reinstall: `pip install -e .`
  4. Restart `webux serve` — tab appears automatically
- **Add CLI command**: create `commands/<name>/register.py`, implement `register(plugin_manifests) -> CommandManifest`
- **Add API routes to an existing plugin**: add `@router.get/post/put` handlers in `webux/<name>/plugin.py`

## 📚 Related Documentation
- See `README.md` for installation, serve options, and per-tab usage
- See `common/AGENTS.md` for shared infrastructure (structlog, config, webux base classes)
