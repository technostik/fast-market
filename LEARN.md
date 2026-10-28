# Learn Log

## 2026-09-25 — video-cli documentation

- Reused the `sound-cli` and `image-cli` documentation structure while treating the video command implementations and `video --help` output as the source of truth.
- Documented all nine discovered commands, local versus Modal routing, stdout/stderr contracts, integrations, troubleshooting, and extension points.
- Verified the documented command surface with `video --help` and each command's `--help` output.
- Baseline test run: 10 tests passed; 6 media regression tests could not run because `moviepy` and `faster_whisper` are not installed in the current environment.
- Keep future CLI documentation synchronized with the root tool index and verify claims against the current help text before publishing.

## 2026-10-10 — long_publish webm

- The long-publish file list follows `youtube.publish.video_extensions`. Adding `.webm` to the code default does nothing for a profile that still has the saved legacy value `mp4,mkv`.
- Migrate only that exact legacy set (order and spacing ignored). Leave every other saved list alone, including a deliberate `mp4`-only list.
- `GET /config` is the write point. Stub `_migrate_publish_cfg_if_needed` in config tests so they do not rewrite `~/.config/fast-market/profiles/*/youtube/config.yaml`.
- The same `video_extensions` key feeds short_publish. A long-publish migration also changes which files short_publish lists.

## 2026-10-10 — Chrome WebM duration

- Chrome MediaRecorder WebM reports `Duration: N/A`. MoviePy aborts in `ffmpeg_parse_infos` before silence removal starts. The packets still have timestamps.
- Reproduce the header with `ffmpeg -f webm -live 1`. A normal ffmpeg WebM writes a duration and hides the bug.
- Feed MoviePy the shorter of the audio and video packet ends. Patch both `ffmpeg_reader.ffmpeg_parse_infos` and `audio.io.readers.ffmpeg_parse_infos`; the audio reader keeps its own import binding.
- Keep the Modal copy inside `remote_steps.py`. The worker image does not contain the `commands` package.

## 2026-10-10 — long_publish retry

- `completed_steps` in `*-long-meta.json` is the resume log. The next run starts at the first index that is neither completed nor skipped. For this video that is step 3, Generate thumbnail.
- An empty thumbnail engine follows the image CLI default. On this profile that default is `flux2cloud`, so a retry without picking `flux2` hits the same quota.

## 2026-10-28 — yt thumbnail engines

- Active profile `techno_sophia` stored `engines.flux2.model_path: black-forest-labs/FLUX.2-12B`. That repo 404s. The local Klein 4B weights are `~/YouTools/flux2-klein-4b` and the Hugging Face snapshot `black-forest-labs/FLUX.2-klein-4B`. `flux2` now prefers those when the configured id is not on disk.
- The same profile had empty `flux29bcloud.account_id` / `api_token`, and no `flux2cloud` block. The interactive shell had `CLOUDFLARE_ACCOUNT_ID`, but `webux serve` did not, so the thumbnail subprocess still failed. Cloud plugins now fall back to those env vars, and the profile file holds the values the server can read.
- A reference image does not change either failure. Both errors happen before the image is posted.
- Thumbnail compose no longer requires a video. The video picker lives in Publish and is checked only on push.

## 2026-10-24 — shell completion startup

- `eval "$(_{CMD}_COMPLETE=bash_source cmd)"` is unsafe to source from an interactive shell. `browser` on PATH is browser-use. On a terminal it prints a welcome text to stdout, and the indented `<<'PY'` example in that text launches Chrome.
- Close stdin, drop stderr, and eval only when the output contains a Click completion marker (`complete -`, `compdef `, `complete --`). Skip paths under `browser-use`.
- A backslash-newline inside `export LD_LIBRARY_PATH=...` keeps the next line's indent as a second argument. Keep that assignment on one line.
