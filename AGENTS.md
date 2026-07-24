# Fast Marketing Tool

Tool with pluggable input and output to help market content for web creators

## CLI Tools

| Tool | Directory | Purpose |
|------|-----------|---------|
| `corpus` | `corpus-cli/` | Content indexing and search |
| `monitor` | `monitor-cli/` | Rule-based source monitoring |
| `youtube` | `youtube-cli/` | YouTube Data API operations |
| `image` | `image-cli/` | AI image generation |
| `sound` | `sound-cli/` | TTS and music generation |
| `message` | `message-cli/` | Telegram messaging |
| `prompt` | `prompt-cli/` | LLM prompt management |
| `task` | `task-cli/` | Agentic task execution |
| `skill` | `skill-cli/` | Skill management |
| `toolsetup` | `toolsetup-cli/` | Tool configuration |
| `websearch` | `websearch-cli/` | Web search via pluggable providers (Google News, Reddit, Hacker News) |
| `rag` | `rag-cli/` | Vectorless reasoning-based RAG with hierarchical document trees |

# Coding rules

See .doc/GOLDEN_RULES.md

# Timeout Policy

See ADR 009: `_doc/adr/009-timeout-policy.md`

## Three-layer summary

| Layer | What it limits | Default | Config location |
|-------|---------------|---------|-----------------|
| L1 — LLM call | One HTTP call to an LLM provider | warn at 3min, kill at 10min | `~/.config/fast-market/common/agent/config.yaml`: `llm_call_warn`, `llm_call_timeout` |
| L2 — Subprocess failsafe | Any subprocess/agent command | 900s (15min) | `~/.config/fast-market/common/agent/config.yaml`: `default_timeout`; or per-skill `SKILL.md`: `timeout:` |
| L3 — Monitor run budget | Total wall time for one `monitor run` | alert at 15min, kill at 30min | `~/.config/fast-market/monitor/config.yaml`: `timeout` block |

## Override per-invocation

```bash
prompt apply my-prompt --timeout 300          # L1: hard LLM timeout 5min
prompt batch-apply -n p -o out -f in.json --timeout 0  # L1: no LLM timeout
skill run "task" --timeout 1800               # L2: 30min per skill step
```

Set `timeout: 0` in `SKILL.md` frontmatter to disable L2 for a specific skill.

## When to change defaults

- A skill legitimately runs longer than 15min: set `timeout: 0` in its `SKILL.md`.
- A batch operation needs more LLM time: set `llm_call_timeout: 0` in agent config or pass `--timeout 0`.
- `monitor run` cron budget needs adjusting: edit `timeout.max` in `monitor/config.yaml`.
- Do NOT simply raise the global `default_timeout` beyond 900s — use per-skill overrides.
