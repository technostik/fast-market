# ADR 009: Three-Layer Timeout Policy

## Status
Accepted

## Context

A `prompt batch-apply` call inside `auto-batch-transcript` was killed by a 60-second subprocess timeout, leaving `hot_transcripts.json` without the `reply_context` field that the downstream skill needed. This caused a cascade failure: the next skill in the pipeline got `ValueError: Missing required arguments: REPLY_CONTEXT`.

The root cause: default timeouts throughout the codebase (60s for subprocess commands, 300s for skill-run) were set for interactive use and are far too short for LLM batch operations that legitimately take several minutes. At the same time, completely removing timeouts creates the risk of silent hangs — especially for `monitor run`, which is invoked by cron and has no human watching it.

## Decision

Three independent timeout layers, each with a distinct purpose:

### Layer 1 — LLM HTTP Timeout (per-call)

Configured in `~/.config/fast-market/common/agent/config.yaml`:

```yaml
llm_call_warn: 180      # seconds — log warning to stderr if call exceeds this
llm_call_timeout: 600   # seconds — hard HTTP timeout passed to LLMRequest
```

**Purpose**: Detect genuinely slow or hung LLM HTTP calls. A call completing in 3–9 minutes is suspicious but allowed (with a warning). A call taking more than 10 minutes is considered a hang.

**Implementation**: `prompt apply` and `prompt batch-apply` load these values, pass `timeout` to `LLMRequest`, and print a warning to stderr when elapsed time exceeds `llm_call_warn`.

### Layer 2 — Subprocess Failsafe (per command)

All subprocess-level default timeouts raised from 60s/300s to **900 seconds (15 minutes)**:

| File | Symbol | Old | New |
|------|--------|-----|-----|
| `skill-cli/core/runner.py` | `execute_skill_script` default | 60s | 900s |
| `skill-cli/core/runner.py` | `execute_skill_run` per-command | 60s | 900s |
| `skill-cli/core/runner.py` | `execute_skill_prompt` total | 300s | 900s |
| `skill-cli/core/runner.py` | agent `default_timeout` fallback | 60s | 900s |
| `skill-cli/commands/run/register.py` | `skill_timeout` | 300s | 900s |
| `prompt-cli/commands/setup/__init__.py` | `default_timeout` setdefault | 60s | 900s |
| `prompt-cli/commands/setup/register.py` | `default_timeout` in default config | 60s | 900s |
| `common/agent/loop.py` | `TaskConfig.default_timeout` | 60s | 900s |
| `common/agent/call.py` | `agent_call` parameter default | 60s | 900s |
| `common/agent/executor.py` | `execute_command` timeout default | 60s | 900s |
| `~/.config/fast-market/common/agent/config.yaml` | `default_timeout` | 60 | 900 |

**Why 15 minutes?** A realistic worst case for a single pipeline step:
- LLM call (Layer 1 limit): up to 10 minutes
- Shell overhead, output, API latency: 1–2 minutes
- Buffer: remaining margin to 15 minutes

Layer 2 is a last-resort failsafe. If a step exceeds 15 minutes, it has gone wrong by definition. If a specific skill legitimately needs more (large batch), set `timeout: 0` in that skill's `SKILL.md` frontmatter.

**1-hour (3600s) was rejected**: 1h means a hung process blocks the entire pipeline for an hour with no feedback. 15 minutes provides a reasonable bound while still allowing real work to complete.

### Layer 3 — Monitor Run Budget (per monitor invocation)

Configured in `~/.config/fast-market/monitor/config.yaml`:

```yaml
timeout:
  alert_after: 15m
  max: 30m
  increment: 5m
  alert_cmd: "message alert 'monitor run: {elapsed}min elapsed — run `monitor wait` (+5min) or `monitor stop`'"
```

**Purpose**: `monitor run` is invoked by cron with no human watching. It can trigger `skill exec` actions that each run their own LLM agent loop. Without a budget, a single long-running action could block all future cron invocations.

**Implementation**: `_run_action_with_budget` in `monitor-cli/commands/run/register.py` runs each action in a background thread while the main thread monitors elapsed time:
- At `alert_after`: runs `alert_cmd` with `{elapsed}` replaced by integer elapsed minutes (sends Telegram alert)
- At `max`: terminates the action and exits
- The user can extend the deadline by `increment` by running `monitor wait` (writes sentinel file `/tmp/fast-market-monitor.wait`)
- The user can abort immediately with `monitor stop` (writes sentinel file `/tmp/fast-market-monitor.stop`)

### Layer 4 — Per-invocation Override

All three entry points support `--timeout` to override the default:

| Command | Option | Effect |
|---------|--------|--------|
| `prompt apply` | `--timeout <secs>` | Overrides `llm_call_timeout` for this call |
| `prompt batch-apply` | `--timeout <secs>` | Overrides `llm_call_timeout` per record |
| `skill run` | `--timeout <secs>` | Overrides `skill_timeout` per skill step |

Pass `--timeout 0` to disable timeout entirely for a single invocation.

## Rationale

The three layers are independent by design:
- Layer 1 (LLM timeout) fires for slow HTTP calls regardless of what triggered them
- Layer 2 (subprocess failsafe) fires for any subprocess that exceeds 15 minutes
- Layer 3 (monitor budget) fires when a `monitor run` invocation as a whole runs too long

They do not derive from each other because the math doesn't work out: with 20 records × 3-minute LLM calls = 60 minutes, a monitor-run total budget of 15 minutes would be wrong for batch jobs. The layers address different failure modes.

## Consequences

- `auto-batch-transcript` and similar pipelines no longer time out prematurely
- Runaway `monitor run` invocations are bounded and the user is notified via Telegram
- Any skill that needs longer than 15 minutes must opt out explicitly with `timeout: 0` in `SKILL.md`
- Per-invocation `--timeout 0` is available as an escape hatch for ad-hoc long runs
