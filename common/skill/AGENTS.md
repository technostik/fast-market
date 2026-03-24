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

## Do NOT
- Add CLI logic here
- Add LLM dependencies here
- This module has zero dependencies beyond pathlib and yaml