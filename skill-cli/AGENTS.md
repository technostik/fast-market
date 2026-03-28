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
- `commands/run/register.py` — Execute skill scripts
- `commands/apply/register.py` — Apply skill to context
- `commands/auto_learn/register.py` — Auto-generate LEARN.md
- `commands/path/register.py` — Print skills directory path
- `commands/params.py` — Custom Click types (`SkillNameType`, `SkillFileType`)

## 📋 Core Responsibilities
- Provide CRUD operations for skills (create, list, show, delete, edit)
- Execute skill scripts with proper path validation
- Manage skill metadata via YAML frontmatter in SKILL.md
- Support LEARN.md for learned information (separate from SKILL.md)
- Validate file paths to prevent directory traversal attacks
- Work standalone without LLM or config dependencies

## 🔗 Dependencies & Integration
- Imports from: `common.core.paths`, `common.skill.skill`, `click`
- Used by: Standalone CLI entry point (`cli/main.py`)
- External deps: `click`

## ✅ Do's
- Always validate paths are within skill directory (prevent directory traversal)
- Use `click.echo()` for output, `err=True` for errors
- Use `sys.exit(1)` for fatal errors after error message
- Support `--learned` / `-l` flag for LEARN.md operations (see `show` and `edit`)
- Use `--create` / `-c` flag for creating files that don't exist
- Include short forms for options: `-l` for `--learned`, `-c` for `--create`
- Keep commands thin — delegate to `common.skill.skill.Skill` for logic
- Use `CommandManifest` dataclass to return commands

## ❌ Don'ts
- Add LLM calls — keep this tool LLM-free
- Add task execution logic — use `run` command for scripts
- Depend on prompt-agent or task-agent
- Accept file paths outside skill directory
- Hardcode skill directory path — use `get_skills_dir()`
- Re-implement skill loading — use `Skill.from_path()`

## 🛠️ Extension Points

### Add New Command
1. Create `commands/<name>/__init__.py` (empty)
2. Create `commands/<name>/register.py` with `register(plugin_manifests) -> CommandManifest`
3. Define Click command with options, use standard short forms (`-l`, `-c`, etc.)
4. Import and use `CommandManifest(name="<name>", click_command=cmd)`

### Add New Option to Existing Command
- Add `@click.option()` decorator before the callback function
- Follow existing patterns: `--learned` / `-l` for LEARN.md, `--create` / `-c` for creation
- Update help text to be clear and concise

### Add Skill File Type
- Add validation logic to `commands/params.py`
- Ensure path stays within skill directory (defense in depth)

## 📚 Related Documentation
- See `common.skill.skill.Skill` for skill loading and metadata handling
- See `common.core.paths.get_skills_dir()` for skills directory location
- See `corpus-cli/commands/AGENTS.md` for command architecture patterns
- See `GOLDEN_RULES.md` for core principles (DRY, KISS, CODE IS LAW, FAIL LOUDLY)
