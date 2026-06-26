# ADR 011: Multiple Profiles (Personas)

## Status

Accepted

## Context

The whole toolchain (corpus, monitor, youtube, image, sound, message, prompt,
task, skill, browser, …) was built around a single identity:

- one YouTube/Substack/Twitter/Telegram account,
- one set of free-service API keys (Groq, image-gen, Whisper, remote python),
- one prompt library, one skill set, one browser session,
- one corpus / voice database.

We want to run **several independent personas** from the same installation:
different accounts, different keys, different prompts/skills, different corpus
data — without cross-contamination. A persona must be clonable so a new one can
start from a copy of an existing one and then diverge.

Three properties of the existing code make this tractable:

1. **`common/core/paths.py`** is the single source of truth for *every*
   filesystem path (config, data, cache, prompts, skills, browser-commands,
   youtube creds/tokens). Inject the profile there and config **and data and
   cache** all isolate at once — including the corpus DB, monitor DB, prompt DB,
   sound reference voices, and every `common/storage/base.py` SQLite database.
2. **`common/core/config.py`** already deep-merges layered config
   (common → discovered sub-configs → tool). Adding a "shared base → profile
   override" layer fits the existing pattern.
3. **`common/cli/base.py::create_cli_group()`** builds the CLI for all tools, so
   one global `--profile` flag covers every CLI.

## Decision

### A profile is a directory namespace

```
~/.config/fast-market/
├── active_profile                     # pointer file: contains "joriel"
├── profiles/
│   ├── _shared/                       # base layer, inherited by every profile, never "active"
│   │   ├── config.yaml                # workdir, global defaults, Anthropic key (inline)
│   │   ├── common/llm/config.yaml
│   │   ├── prompts/ skills/ browser-commands/   # shared resources (fallbacks)
│   ├── joriel/                        # the migrated current setup
│   │   ├── config.yaml                # inline free-service keys, overrides
│   │   ├── common/youtube/{config.yaml,client_secret.json,token.json}
│   │   ├── prompts/ skills/ browser-commands/   # persona-specific resources
│   └── <other personas>/ …
~/.local/share/fast-market/profiles/<name>/{prompts,skills,browser-commands,data,...}
~/.cache/fast-market/profiles/<name>/...
```

`_shared` is a reserved profile name: it is the inheritance base and is **never
the active profile**. There is no automatically-created `default` profile; a
profile literally named `default` only exists if the user creates it explicitly,
and starts empty.

### Active-profile resolution (first match wins)

1. `--profile <name>` global CLI flag (exports `FASTMARKET_PROFILE` for the process)
2. `FASTMARKET_PROFILE` environment variable
3. `~/.config/fast-market/active_profile` pointer file
4. fallback constant `"default"`

After migration the pointer file contains `joriel`, so `joriel` is active by
default — behaving exactly like the pre-profile setup.

### Config: shared base + profile override

`load_tool_config()` builds the merge chain:

```
_shared common config + _shared sub-configs
  → <profile> common config + <profile> sub-configs
  → tool config
```

Later layers win (deep merge). Enter the Anthropic key once in `_shared`; rotate
free-service keys per profile.

`workdir` / `workdir_root` live in `_shared/config.yaml`, so the working
directory is **shared across profiles** by default (it is usually a throwaway
temp dir); a profile may override it if ever needed.

### Secrets: inline in config

Keys are stored inline in `config.yaml` (`api_key`, `api_token`, `bot_token`).
`image-cli` (`api_token`) and `message-cli`/Telegram (`bot_token`) already do
this, so they isolate for free once config is profile-scoped. The five LLM
providers gain an inline `api_key` path that is resolved **before** the existing
`api_key_env` / `.env` fallback, so the Anthropic key can live in `_shared` and
free-service keys per profile.

### Resources (prompts / skills / browser-commands): union with shadowing

These are file collections, not single values, so they use **ordered search
dirs** `[<profile>, _shared]`:

- **lookup by name**: profile first, then `_shared` — a profile resource shadows
  a shared one of the same name.
- **list**: union of both, de-duplicated by name, profile wins; shared-only
  entries are tagged `(shared)`.
- **create / write / delete**: target the **profile** dir by default; a
  `--shared` flag targets `_shared`.

### Paths that bypassed `paths.py` (fixed)

These hardcoded `Path.home()` and would have leaked across profiles:

- `common/youtube/auth.py` — youtube auth dir (client_secret + token)
- `common/youtube/transport.py` — token path
- `browser-cli` — Chrome `user_data_dir` (`~/.chrome-debug-profile`)

All now route through `paths.py` and isolate per profile (the browser session
included, so logins/cookies don't collide).

### Tooling

`toolsetup profile` subcommands:

- `list` — list profiles + mark the active one
- `show-shared` — show the `_shared` base
- `show-path` — print resolved config/data/cache paths for a profile
- `create <name>` — new empty profile
- `clone <src> <dst>` — copy a profile to a new one
- `delete <name>` — remove a profile (guards active / `_shared`)
- `use <name>` — write the `active_profile` pointer
- `migrate` — one-time move of a legacy (pre-profile) layout into `joriel` and
  set the pointer

## Consequences

- Data is isolated per profile automatically via `paths.py`; the corpus/voice DB
  cannot leak between personas.
- One installation, many personas, switchable per-command (`--profile`),
  per-shell (`FASTMARKET_PROFILE`), or globally (pointer file).
- `_shared` removes duplication for things common to all personas (paid LLM key,
  workdir, shared prompts/skills/scripts).
- The migration is the moment profiles "turn on": before it, a legacy layout
  could still be read via the `default` fallback; after it, `joriel` is active.
- Tests pin an explicit profile and fixtures live under `profiles/<name>/`.
