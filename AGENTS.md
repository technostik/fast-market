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
| `video` | `video-cli/` | Video processing and publishing pipeline |
| `message` | `message-cli/` | Telegram messaging |
| `prompt` | `prompt-cli/` | LLM prompt management |
| `task` | `task-cli/` | Agentic task execution |
| `skill` | `skill-cli/` | Skill management |
| `toolsetup` | `toolsetup-cli/` | Tool configuration |
| `websearch` | `websearch-cli/` | Web search via pluggable providers (Google News, Reddit, Hacker News) |
| `rag` | `rag-cli/` | Vectorless reasoning-based RAG with hierarchical document trees |

# Code quality

Do not vendor the tools here. Clone the private sibling repo next to this project
(`../agent-dev-tools`) or set `AGENT_DEV_TOOLS`.

Skill: [`../agent-dev-tools/skills/evaluate-code-quality/SKILL.md`](../agent-dev-tools/skills/evaluate-code-quality/SKILL.md)

GOLDEN_RULES **MEASURABILITY**: track complexity × churn on touched files.

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

---

## 📋 Quick Reference: YouTube Multi-Account OAuth

When creating a new profile for a **different Google account**:

1. `FASTMARKET_PROFILE=newprofile toolsetup`  (auto-creates YouTube config)
2. Copy or create `client_secret.json` in `~/.config/fast-market/profiles/newprofile/common/youtube/`
3. **If sharing OAuth app**: Add the new email as **test user** in Google Cloud Console → OAuth consent screen
4. `FASTMARKET_PROFILE=newprofile youtube setup refresh-auth`

**Docs**: [README.md#-youtube-oauth-for-multi-account-profiles](README.md#-youtube-oauth-for-multi-account-profiles), [youtube-cli/README.md](youtube-cli/README.md#oauth-consent-screen-for-multiple-profilesaccounts), [toolsetup-cli/README.md](toolsetup-cli/README.md#️-youtube-oauth-setup-for-new-profiles)
