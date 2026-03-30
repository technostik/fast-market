# skill-cli/core Module

## Purpose
Core execution and orchestration logic for skill-cli. Responsible for:
- Loading and discovering skills (`skill.py`)
- Executing skills and tasks directly in-process (`runner.py`)
- Orchestrating multi-skill pipelines (`router.py`)

## Architecture

```
core/
├── skill.py      — Skill data class and discovery
├── runner.py     — Single-skill execution (script, run:, prompt)
└── router.py     — Multi-step orchestration loop
```

---

## router.py

### Design

The router has three phases:

1. **Preparation** — runs once before the loop. The LLM reads the goal and
   available skills, then produces a structured execution plan with
   `success_criteria` (what done looks like) and `risks`.
2. **Planning loop** — at each iteration, calls an LLM to decide what to do
   next, executes that action in-process (no subprocess), distills the result,
   and feeds it back to the next plan call.
3. **Evaluation** — runs after each step. The LLM checks whether the result
   matches the success criteria. If satisfied, the router stops early.

### Actions the planner can emit

| Action | What it does |
|--------|-------------|
| `run`  | Execute a named skill directly via `_run_skill()` |
| `task` | Execute a free-form description via `_run_task()` (raw CLI tools, no skill wrapper) |
| `ask`  | Ask the user a question via the `InteractionPlugin` |
| `done` | Goal achieved — stop |
| `fail` | Goal cannot be achieved — stop with failure |

### Why `task` exists
Use it when no skill fits perfectly, or when a skill failed and the planner wants
to improvise with raw tools (ls, grep, jq, yt-dlp, etc.) directly.

### Context threading
Each step produces two outputs:
- `runner_summary` (≤15 lines) — fed to the planner for decision-making
- `context` (richer extract) — passed to the next step so it has relevant data

Both are produced by LLM calls (`_call_runner_summary`, `_call_context_extract`).
Context flows as `prev_context` and is injected into the next skill/task description.
For skills it is also injected as the `_router_context` param so the skill's own
LLM can see it.

### No subprocess
Skills and tasks are executed **in-process** via `TaskLoop` from `common.agent`.
There is no session YAML written to disk for IPC — the `Session` object is
returned directly and converted to text via `_session_to_text()`.
The cache dir `~/.cache/fast-market/skill-router/` is no longer used.

### Workdir isolation
Each step still creates an isolated subdirectory: `{workdir}/{iteration:02d}_{label}/`
This is filesystem hygiene, not IPC. Scripts and LLM tool calls work inside that dir.

### InteractionPlugin
```python
class InteractionPlugin:
    def ask(self, question: str) -> str: ...

class CLIInteractionPlugin(InteractionPlugin):
    # default: uses input() on terminal
```

Pass a custom plugin to `run_router(interaction=MyPlugin())` to route questions
to Telegram, a web UI, etc.

### Prompts

The router uses three prompt templates:
- `PREPARATION_PROMPT` — produces plan, success_criteria, risks
- `PLAN_PROMPT` — decides next action (includes success_criteria from preparation)
- `EVALUATION_PROMPT` — checks if last step satisfied success_criteria

These are configurable via `skill setup preparation-prompt` and
`skill setup evaluation-prompt`. Use `--no-eval` flag to skip evaluation
entirely for fast/cheap runs.

---

## runner.py

### execute_skill_prompt()
Runs the skill's SKILL.md body as a task description through `common.agent.TaskLoop`.
Uses `init_skill_agent_config()` to get allowed commands and prompt templates.
Returns a `SkillResult`.

### execute_skill_script()
Runs a script file under `scripts/` with SKILL_* env vars set.

### execute_skill_run()
Runs the `run:` frontmatter inline command with `{param}` substitution.

---

## skill.py

Loads skills from `~/.local/share/fast-market/skills/`.
`Skill.from_path()` reads SKILL.md frontmatter and body.
`discover_skills()` scans the directory.

---

## Do's
- Import `execute_skill_prompt` from `core.runner` for single-skill execution
- Import `run_router` from `core.router` for multi-skill orchestration
- Use `InteractionPlugin` subclass to customize user interaction
- Skills run in isolated subdirectories — always pass `subdir` as workdir

## Don'ts
- Do NOT call `skill apply` via subprocess from the router — use `_run_skill()` directly
- Do NOT write session YAML to disk for IPC — use the returned Session object
- Do NOT put orchestration logic in `runner.py` — that belongs in `router.py`
- Do NOT hardcode the interaction channel — always go through `InteractionPlugin`
