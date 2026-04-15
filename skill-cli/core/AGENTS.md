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
Each step creates an isolated subdirectory: `{run_root}/{iteration:02d}_{label}/`
where `run_root = {workdir_root}/skill_run_{uuid}/` (or `{workdir}/skill_run_{uuid}/` if `workdir_root` is not configured).

This ensures:
- Sequential or concurrent runs using the same workdir do not collide
- The router session file (`router.session.yaml`) lives inside `run_root`, not directly in workdir
- All filesystem writes go into `run_root`; the external `workdir` argument is only used for logging
- Isolated runs are placed in `workdir_root` to keep them separate from regular work

If `run_root.mkdir` fails, the exception propagates — fail loudly.

### Session persistence with `--save-session`
When `--save-session` flag is passed to `skill run`, the router aggregates all skill
execution sessions into a single `router.session.yaml` file in `run_root`.

The aggregation process:
1. After the router completes (or fails/max iterations reached), it scans `run_root`
2. Finds all subdirectories matching the pattern `XX_*` (two digits + underscore)
3. Looks for `*.session.yaml` files in each subdir (written by individual skill runs)
4. Aggregates all turns into a single Session object
5. Saves to `{run_root}/router.session.yaml`

The aggregated session contains:
- `task_description`: The original goal
- `turns`: All LLM turns from all skills and tasks
- `exit_code`: 0 if goal was achieved, 1 otherwise
- `end_reason`: Why the session ended (completed/failed/max iterations)

This file can be used with `skill create auto-from-session` to create a new skill
that reproduces the pipeline.

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
