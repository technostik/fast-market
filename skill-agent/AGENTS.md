# skill-agent

## Purpose
Standalone CLI to manage skills stored in ~/.local/share/fast-market/skills/.
Skills are directories containing SKILL.md (with YAML frontmatter) and an
optional scripts/ subdirectory.

## Commands
- skill list           — list all skills
- skill show <name>    — show skill details
- skill create <name>  — scaffold a new skill
- skill delete <name>  — remove a skill
- skill path           — print skills directory path

## Dependencies
- common.core.paths (get_skills_dir)
- common.skill.skill (Skill, discover_skills)
- NO LLM dependency
- NO config dependency (works without global-setup)

## Do NOT
- Add LLM calls here
- Add task execution here
- Depend on prompt-agent or task-agent