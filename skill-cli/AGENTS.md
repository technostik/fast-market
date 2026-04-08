# skill-agent

## 🎯 Purpose
Standalone CLI to manage skills stored in `~/.local/share/fast-market/skills/`. Skills are directories containing `SKILL.md` (with YAML frontmatter), optional `LEARN.md`, and a `scripts/` subdirectory for executable files.

## 🏗️ Essential Components
- `cli/main.py` — Entry point, registers all commands via `discover_commands()`
- `commands/base.py` — `CommandManifest` dataclass for command registration
- `commands/list/register.py` — List all skills
- `commands/show/register.py` — Show skill details, supports `--learn` for LEARN.md
- `commands/create/register.py` — Scaffold new skill
- `commands/delete/register.py` — Remove skill
- `commands/edit/register.py` — Edit skill files, supports `--learn` for LEARN.md and `--shell` for scripts/run.sh
- `commands/run/register.py` — Orchestrate multiple skills (LLM-powered) with isolated subdirs
- `commands/apply/register.py` — Apply/execute a skill
- `commands/auto_learn/register.py` — Auto-learn templates and compact command
- `commands/path/register.py` — Print skills directory path
- `commands/params.py` — Custom Click types (`SkillNameType`, `SkillFileType`, `SkillRefType`, `SkillParamType`)
- `commands/setup/register.py` — Skill agent config (allowed commands, prompt templates)
- `commands/setup/__init__.py` — load/save/init skill agent config
- `commands/setup/skill_edit.py` — editor + validation for agent config

## 📋 Core Responsibilities
- Provide CRUD operations for skills (create, list, show, delete, edit)
- Execute skill scripts with proper path validation
- Manage skill metadata via YAML frontmatter in SKILL.md
- Support LEARN.md for learned information (separate from SKILL.md)
- Auto-learn: Extract lessons from executions using LLM
- Auto-compact: Consolidate LEARN.md when exceeding line threshold
- Validate file paths to prevent directory traversal attacks
- Work standalone, delegate LLM operations to common/learn

## skill run coordination model

### Isolation Modes
The router supports three isolation modes for skill execution directories:

- **Default (`isolation_mode="none"`)**: All skills execute directly in the workdir. Skills can see and modify each other's files, enabling file-based cooperation.
- **`--run-isolated`**: Creates one isolated directory `{workdir}/run_{uuid}/` for the entire run. All skills share this directory.
- **`--skill-isolated`** (current default behavior): Creates `{workdir}/run_{uuid}/` with subdirectories `{iteration:02d}_{skill_name}/` for each skill. Skills cannot see each other's files.

### Context Passing
- Two-part distillation: `runner_summary` (≤15 lines for planner) + `context` (transferable to next skill)
- Planner can provide `context_hint` to guide context extraction
- The router passes `_router_context` param to skills with the previous skill's context

### Shared Context (optional)
When `--shared-context` is enabled, skills gain access to a `shared_context` tool that provides a cooperative string all skills can read and write:

- **read** — Returns current context content
- **write** — Replaces the entire context
- **append** — Adds content to the existing context
- **clear** — Empties the context

The router injects into each skill's prompt:
- The global task objective
- Current context state
- Instructions to write key results so downstream skills can use them

This enables skills to cooperate by passing structured information beyond file outputs.

### Auto-Skills (plan convert-task-to-skill)
Named tasks (with a `name` field) can be converted to persistent auto-skills using the `skill plan convert-task-to-skill` subcommand:

- **Creation**: `skill plan convert-task-to-skill run.yaml` creates `auto-{name}` skills
- **Parameters**: `{{key}}` and `{{key:default}}` placeholders in the description become skill parameters
- **Summary**: A one-sentence description is generated via LLM
- **Persistence**: Once created, auto-skills are reused across runs
- **Reset**: `--reset` forces recreation of existing skills

The `_create_auto_skill()` function in `commands/run-plan/register.py` handles auto-skill creation:
1. Extracts parameters from `{{placeholders}}` in the task description
2. Calls LLM for a one-sentence summary
3. Writes SKILL.md with parameters, summary, and converted body (`{{key}}` → `{key}`)

### Run Statistics
At the end of each run, statistics are calculated and displayed:
- **Timing**: Total run time (tracked via `start_time` and `end_time` in RouterState)
- **Steps**: Total steps executed, broken down by successful/failed/skipped
- **Actions**: Skill executions, task executions, user questions
- **Skills**: Count of unique skills executed

Statistics are computed by `calculate_run_statistics()` and formatted by `format_statistics()` in `core/router.py`.

## SKILL.md Frontmatter Options
- `name` — Skill name (defaults to directory name)
- `description` — Brief description
- `max_iterations` — Max LLM iterations for prompt-based skills
- `timeout` — Execution timeout in seconds (0 = no timeout)
- `llm_timeout` — LLM call timeout in seconds
- `autocompact` — Auto-compact LEARN.md when exceeding this many lines
- `stop_condition` — Custom completion criteria that tells the LLM when the task is done. Injected into the task body and helps prevent early termination. Example:
  ```yaml
  stop_condition: |
    - You executed the command and got a result
    - NOT just figured out the answer in your head and returned it as text
  ```

## 🔗 Dependencies & Integration
- Imports from: `common.core.paths`, `common.skill.skill`, `common.learn`, `click`
- Used by: Standalone CLI entry point (`cli/main.py`)
- External deps: `click`, `pyyaml`

## ✅ Do's
- Always validate paths are within skill directory (prevent directory traversal)
- Use `click.echo()` for output, `err=True` for errors
- Use `sys.exit(1)` for fatal errors after error message
- Support `--learn` / `-l` flag for LEARN.md operations (see `show` and `edit`)
- Use `--create` / `-c` flag for creating files that don't exist
- Include short forms for options: `-l` for `--learn`, `-c` for `--create`, `-C` for `--compact`
- Keep commands thin — delegate to `common.skill.skill.Skill` for logic
- Use `CommandManifest` dataclass to return commands
- Use `SkillNameType()` for skill name arguments with autocomplete
- Use `common.learn` for LLM-based learning functionality
- Use `init_skill_agent_config()` in execute_skill_prompt() to get allowed commands

## ❌ Don'ts
- Add inline LLM logic — use `common.learn` functions instead
- Add task execution logic — use `run` or `apply` command
- Accept file paths outside skill directory
- Hardcode skill directory path — use `get_skills_dir()`
- Re-implement skill loading — use `Skill.from_path()`
- Skip `requires_common_config()` for LLM-dependent commands
- Do not read task-cli config in skill-cli; use skill's own agent config

## 🛠️ Extension Points

### Add New Command
1. Create `commands/<name>/__init__.py` (empty)
2. Create `commands/<name>/register.py` with `register(plugin_manifests) -> CommandManifest`
3. Define Click command with options, use standard short forms (`-l`, `-c`, etc.)
4. Import and use `CommandManifest(name="<name>", click_command=cmd)`
5. Use `SkillNameType()` for skill name arguments to enable autocomplete

### Add New Option to Existing Command
- Add `@click.option()` decorator before the callback function
- Follow existing patterns: `--learn` / `-l` for LEARN.md, `--shell` / `-s` for scripts/run.sh, `--create` / `-c` for creation
- Update help text to be clear and concise

### Add Skill File Type
- Add validation logic to `commands/params.py`
- Ensure path stays within skill directory (defense in depth)

### Use LLM Learning
- Import from `common.learn`: `analyze_session`, `update_learn_file`, `compress_learn_content`
- Use `get_learn_analysis_prompt(config)`, `get_learn_result_template(config)`, `get_learn_compacting_prompt(config)` for templates

## 📚 Related Documentation
- See `common.skill.skill.Skill` for skill loading and metadata handling
- See `common.learn` for LLM-based learning functionality
- See `common.core.paths.get_skills_dir()` for skills directory location
- See `corpus-cli/commands/AGENTS.md` for command architecture patterns
- See `GOLDEN_RULES.md` for core principles (DRY, KISS, CODE IS LAW, FAIL LOUDLY)

## execute_skill_prompt() Implementation

execute_skill_prompt() in core/runner.py uses common/agent.TaskLoop directly
(no subprocess). It reads skill's own agent config via init_skill_agent_config()
from commands/setup/__init__.py. The agent config is stored under the "agent"
key in ~/.config/fast-market/skill/config.yaml, separate from other skill tool
settings (workdir, auto_learn_prompt).

### Injecting Additional Instructions

The `execute_skill_prompt()` function accepts an optional `inject` parameter (string).
When provided, the injected instructions are appended to the skill's task description
as an "## Additional Instructions" section, after:
- The original skill body content
- Parameter substitutions and unconsumed parameters section
- LEARN.md previous lessons (if present)
- Stop condition (if defined)
- **Injected instructions** (if provided via `--inject`)
- Shared context (if enabled)

This allows users to add context-specific guidance without modifying the skill file itself.
The injection is visible in dry-run output under "[DRY RUN] Injected instructions:".
