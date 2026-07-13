# ADR 012: Externalize webux LLM Prompts into the Prompt Store

## Status

Accepted

## Context

The `webux-cli` components that drive LLM generation each defined their prompts differently:

- **short_publish / long_publish** — referenced prompt names in config (`youtube-title`, `youtube-summary`, …) but exposed them in the config UI as free-text `<input>` fields, so the user had to type a name from memory.
- **storyboard** — embedded three full prompt templates inline as Python constants in `config.py` (`_STORY_BREAKDOWN_PROMPT`, `_SCENE_TRANSCRIPT_PROMPT`, `_SCENE_IMAGE_PROMPT`). These were never registered in the `prompt` store, so they were invisible to `prompt list`, not editable with `prompt edit`, and not reusable by other components.
- **yt_poster** — referenced a per-row `prompt-name` metadata field, with no UI affordance to pick a prompt; the only way to change it was via a separate edit modal or by regenerating the dataset.

ADR 004 ("Prompt Service") established `prompt` as the single store for named prompts, with `apply`, `get`, `edit`, `list`, and `create` commands. The webux components were not consistently leveraging it.

**Goal**: externalize every LLM prompt used by any webux component into the `prompt` store, seeded from one YAML, and expose them in each config UI as a **selectbox** listing all available prompts (via `prompt list`). Keep an optional inline override textarea (used only when non-empty, e.g. for quick tests) and show the selected prompt's content on hover.

## Decision

### Seed as single source of truth

`webux-cli/webux/resources/webux_prompts.yaml` is the canonical list of the 17 prompts used across webux (marketing-analysis, youtube-title, youtube-summary, youtube-legalcheck, youtube-short-caption, youtube-short-hashtags, youtube-comment-reply, youtube-comment-analysis, youtube-thumbnail, youtube-thumbnail-overlay, summarize, storyboard-breakdown, storyboard-scene-transcript, storyboard-scene-image, and the two poster prompts). Existing store prompts are copied verbatim; the storyboard and thumbnail prompts (previously inline/empty) are added. The seed lives inside `webux-cli` because these prompts are specific to webux components, not shared with other CLIs.

### Import + list command

`prompt-cli/commands/setup/webux_prompts.py` adds a `webux` group under `prompt setup`:

- `prompt setup webux import` — creates each seed prompt if missing in the active profile; `--force` overwrites existing versions.
- `prompt setup webux list` — prints each seed name with `exists: true/false`.

It is wired into `prompt-cli/commands/setup/register.py`.

### Auto-seed on serve

`webux-cli/commands/serve/register.py` runs `prompt setup webux import --force` (best-effort, `run(..., check=False)`, `--file` pointing at `webux-cli/webux/resources/webux_prompts.yaml`) right after the profile config is loaded. The `--force` means every (re)launch overwrites the stored prompts with the current seed, so edits to the seed propagate automatically. The manual `prompt setup webux import` (no `--force`) stays non-destructive (only creates missing prompts).

### Config UI pattern (short_publish / long_publish / storyboard)

Each prompt field becomes:

1. A `<select>` populated by a `populateConfigPrompts()` / `populateStoryPrompts()` helper that calls a new backend `/list-prompts` endpoint, which shells out to `prompt list --names-only`.
2. An inline override `<textarea>` (kept for quick edits / tests). The backend uses the override **only when non-empty**; otherwise it uses the selected named prompt.
3. A hover `ⓘ` that previews the selected prompt's content via a new `/prompt-content?name=` endpoint (`prompt get <name> --content`).

`long_publish` thumbnail fields additionally offer a "— none —" option.

### storyboard externalization

- `config.py` drops the inline constants; `DEFAULT_PROMPT_NAMES` maps the three keys (`story_breakdown`, `scene_transcript`, `scene_image_prompt`) to `storyboard-breakdown`, `storyboard-scene-transcript`, `storyboard-scene-image`.
- `load_storyboard_config` migrates any legacy inline text in `prompts` into `prompt_overrides` (per-key), so old configs keep working. `prompt_overrides` is added to the save whitelist.
- `pipeline.py` adds `_apply_story_prompt(step, state, config, key, content_file)` which resolves the named prompt from the store and applies it with params (`lang`, `chapter_range`, `scene_range`, `scene_duration`, `narrative_style`, `image_style`) plus `content=@<content_file>`; if the named prompt is missing it falls back to the inline `prompt_overrides` path. The three original call sites now use this helper.
- `register.py` adds `/list-prompts` and `/prompt-content`, returns `prompt_overrides` from `GET /config`, and accepts `prompt_overrides` in `ConfigSaveRequest`. The frontend exposes the select + override + hover per field.

### yt_poster selectbox

- `plugin.py` adds `GET /list-prompts` (same `prompt list --names-only` pattern) and an optional `prompt_name` field on `RegenerateRequest`. The `/regenerate` handler uses `payload.prompt_name or metadata["prompt-name"]`, falling back to the per-row metadata when the selectbox is left at "— from metadata —".
- `register.py` adds a `Prompt:` `<select id="regenPrompt">` in the controls bar, populated by `populateYTPrompts()`, and `regenerateRows` sends its value as `prompt_name`.

## Rationale

**Why one seed YAML + import command?** A single file is the auditable source of truth; the `import` command makes seeding reproducible across machines and CI without manual `prompt create` invocations, and `--force` supports iteration on the templates.

**Why auto-seed on `webux serve`?** Guarantees the store is populated before any component tries to list/apply prompts, removing a manual setup step.

**Why keep the inline override textarea?** Lets users tweak a prompt for a one-off run or a test without mutating the shared store prompt — non-empty override wins, matching the original "free-text" ergonomics while defaulting to managed prompts.

**Why hover preview instead of always-visible text?** Keeps the config panel compact while still surfacing what the selected prompt actually contains (important now that the text is no longer typed inline).

## Consequences

- `webux-cli/webux/resources/webux_prompts.yaml` must stay in sync with the `prompt` store. The store is the runtime source; the YAML is the seed. `prompt setup webux list` surfaces drift (missing prompts) for manual `import --force`.
- storyboard prompts use **doubled braces** for JSON-schema literals (`{{`, `}}`) so `prompt apply` treats them as literal text, while single-brace `{content}`, `{lang}`, etc. remain substitution placeholders.
- `webux serve` startup gains a small, best-effort subprocess call (`prompt setup webux import --force`); failures are logged but do not abort startup. Because it uses `--force`, the store is always re-synced to `webux_prompts.yaml` on every launch — per-run tweaks should use the config-panel inline override, not the store prompt, since they are reset on relaunch.
- Each component's config UI now depends on a `/list-prompts` backend endpoint; if `prompt` is not on `PATH` the selectbox silently stays at its default option.
- yt_poster behavior is unchanged when the selectbox is left at "— from metadata —"; existing per-row `prompt-name` metadata continues to drive regeneration.
