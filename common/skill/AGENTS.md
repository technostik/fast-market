# common/skill

## Purpose
Skill discovery and model. A skill is a directory containing SKILL.md with
YAML frontmatter plus optional scripts/ subdirectory.

Used by:
- skill-agent: manages skills (CRUD)
- task-agent: builds skill documentation for LLM system prompt

## Key functions
- `Skill.from_path(path)` — load skill from directory
- `discover_skills(skills_dir)` — list all skills

## Skill location
~/.local/share/fast-market/skills/ (via common.core.paths.get_skills_dir)

## Router coordination (router.py)
The router orchestrates multiple skill executions with isolated subdirectories:
- Each skill execution runs in `{workdir}/{iteration:02d}_{skill_name}/`
- Planner receives history with subdir paths and copied files info
- Two-part distillation: `runner_summary` (≤15 lines for planner) + `context` (transferable to next skill)
- Context hint from planner guides context extraction
- Files can be copied from previous subdirs via `copy_from` field

## Key dataclasses
- `SkillAttempt`: skill_name, params, exit_code, runner_summary, context, context_hint, success, iteration, subdir, copied_files
- `RouterState`: goal, attempts, iteration, max_iterations, done, final_result, failed, failure_reason

## Do NOT
- Add CLI logic here
- Add LLM dependencies here
- This module has zero dependencies beyond pathlib and yaml