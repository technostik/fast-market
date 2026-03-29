# skill-agent

## 🎯 Purpose
Standalone CLI to manage skills stored in `~/.local/share/fast-market/skills/`. Skills are directories containing `SKILL.md` (with YAML frontmatter), optional `LEARN.md`, and a `scripts/` subdirectory for executable files.

## 🏗️ Essential Components
- `cli/main.py` — Entry point, registers all commands via `discover_commands()`
- `commands/base.py` — `CommandManifest` dataclass for command registration
- `commands/list/register.py` — List all skills
- `commands/show/register.py` — Show skill details, supports `--learned` for LEARN.md
- `commands/create/register.py` — Scaffold new skill
- `commands/delete/register.py` — Remove skill
- `commands/edit/register.py` — Edit skill files, supports `--learned` for LEARN.md
- `commands/run/register.py` — Orchestrate multiple skills (LLM-powered) with isolated subdirs
- `commands/apply/register.py` — Apply/execute a skill
- `commands/auto_learn/register.py` — Auto-learn templates and compact command
- `commands/path/register.py` — Print skills directory path
- `commands/params.py` — Custom Click types (`SkillNameType`, `SkillFileType`, `SkillRefType`, `SkillParamType`)

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
- Each skill execution runs in an isolated subdirectory: `{workdir}/{iteration:02d}_{skill_name}/`
- The planner receives history including subdir paths and copied files info
- Two-part distillation: `runner_summary` (≤15 lines for planner) + `context` (transferable to next skill)
- Planner can provide `context_hint` to guide context extraction
- Planner can specify `copy_from` to copy files from previous subdirs
- The router passes `_router_context` param to skills with the previous skill's context

## SKILL.md Frontmatter Options
- `name` — Skill name (defaults to directory name)
- `description` — Brief description
- `max_iterations` — Max LLM iterations for prompt-based skills
- `timeout` — Execution timeout in seconds (0 = no timeout)
- `llm_timeout` — LLM call timeout in seconds
- `autocompact` — Auto-compact LEARN.md when exceeding this many lines

## 🔗 Dependencies & Integration
- Imports from: `common.core.paths`, `common.skill.skill`, `common.learn`, `click`
- Used by: Standalone CLI entry point (`cli/main.py`)
- External deps: `click`, `pyyaml`

## ✅ Do's
- Always validate paths are within skill directory (prevent directory traversal)
- Use `click.echo()` for output, `err=True` for errors
- Use `sys.exit(1)` for fatal errors after error message
- Support `--learned` / `-l` flag for LEARN.md operations (see `show` and `edit`)
- Use `--create` / `-c` flag for creating files that don't exist
- Include short forms for options: `-l` for `--learned`, `-c` for `--create`, `-C` for `--compact`
- Keep commands thin — delegate to `common.skill.skill.Skill` for logic
- Use `CommandManifest` dataclass to return commands
- Use `SkillNameType` for skill name arguments with autocomplete
- Use `common.learn` for LLM-based learning functionality

## ❌ Don'ts
- Add inline LLM logic — use `common.learn` functions instead
- Add task execution logic — use `run` or `apply` command
- Accept file paths outside skill directory
- Hardcode skill directory path — use `get_skills_dir()`
- Re-implement skill loading — use `Skill.from_path()`
- Skip `requires_common_config()` for LLM-dependent commands

## 🛠️ Extension Points

### Add New Command
1. Create `commands/<name>/__init__.py` (empty)
2. Create `commands/<name>/register.py` with `register(plugin_manifests) -> CommandManifest`
3. Define Click command with options, use standard short forms (`-l`, `-c`, etc.)
4. Import and use `CommandManifest(name="<name>", click_command=cmd)`
5. Use `SkillNameType()` for skill name arguments to enable autocomplete

### Add New Option to Existing Command
- Add `@click.option()` decorator before the callback function
- Follow existing patterns: `--learned` / `-l` for LEARN.md, `--create` / `-c` for creation
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
