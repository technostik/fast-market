from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


class SkillParseError(Exception):
    """Raised when SKILL.md frontmatter YAML is malformed."""

    pass


@dataclass(slots=True)
class Skill:
    """Represents a skill folder following Anthropic's skill format."""

    name: str
    path: Path
    description: str = ""
    has_scripts: bool = False
    parameters: list[dict] = field(default_factory=list)
    run: str | list[str] = ""
    max_iterations: int | None = None
    timeout: int | str | None = (
        None  # Can be seconds (int) or duration string like '10m', '1h'
    )
    llm_timeout: int | str | None = None  # Can be seconds (int) or duration string
    autocompact_lines: int | None = None
    stop_condition: str = ""

    @classmethod
    def from_path(cls, path: Path, strict: bool = False) -> Optional[Skill]:
        """Load skill from directory if valid.

        Args:
            path: Path to skill directory
            strict: If True, raise SkillParseError on malformed YAML.
                   If False, return minimal Skill with empty description.
        """
        skill_file = path / "SKILL.md"
        if not skill_file.exists():
            return None

        content = skill_file.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1])
                    run_value = frontmatter.get("run", "")
                    return cls(
                        name=frontmatter.get("name", path.name),
                        path=path,
                        description=frontmatter.get("description", ""),
                        has_scripts=(path / "scripts").exists(),
                        parameters=frontmatter.get("parameters", []),
                        run=run_value,
                        max_iterations=frontmatter.get("max_iterations"),
                        timeout=frontmatter.get("timeout"),
                        llm_timeout=frontmatter.get("llm_timeout"),
                        autocompact_lines=frontmatter.get("autocompact"),
                        stop_condition=frontmatter.get("stop_condition", ""),
                    )
                except Exception as exc:
                    if strict:
                        raise SkillParseError(
                            f"Failed to parse SKILL.md for '{path.name}': {exc}"
                        ) from exc
                    # Non-strict: fall through to minimal skill

        return cls(name=path.name, path=path, description="")

    def get_execution_mode(self) -> str:
        """Return the execution mode: 'script', 'command', or 'agent'."""
        if self.has_scripts:
            return "script"
        if self.run:
            return "command"
        return "agent"

    def health_check(self) -> list[str]:
        """Return list of health issues found."""
        issues = []
        if not self.description:
            issues.append("missing description")
        if self.has_scripts:
            scripts_dir = self.path / "scripts"
            if not scripts_dir.exists():
                issues.append("has_scripts=true but scripts/ missing")
            else:
                script_files = [p for p in scripts_dir.iterdir() if p.is_file()]
                if not script_files:
                    issues.append("scripts/ directory empty")
        elif not self.run and not (self.path / "SKILL.md").exists():
            issues.append("no scripts, no run: command, no SKILL.md")

        # Check for malformed YAML by attempting strict parse
        skill_file = self.path / "SKILL.md"
        if skill_file.exists():
            content = skill_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        yaml.safe_load(parts[1])
                    except Exception as exc:
                        issues.append(f"malformed frontmatter: {exc}")

        return issues

    def get_body(self) -> str:
        """Return SKILL.md content after the frontmatter block."""
        content = (self.path / "SKILL.md").read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return content.strip()


def discover_skills(skills_dir: Path) -> list[Skill]:
    """Discover all skills in the skills directory."""
    if not skills_dir.exists():
        return []

    skills = []
    for item in sorted(skills_dir.iterdir()):
        if item.is_dir():
            skill = Skill.from_path(item)
            if skill:
                skills.append(skill)
    return skills


def discover_skills_layered(search_dirs: list[Path] | None = None) -> list[Skill]:
    """Discover skills across the active profile then the _shared base.

    A skill in the profile shadows a shared skill of the same directory name.
    """
    if search_dirs is None:
        from common.core.paths import get_skills_search_dirs

        search_dirs = get_skills_search_dirs()

    seen: set[str] = set()
    skills: list[Skill] = []
    for skills_dir in search_dirs:
        if not skills_dir.exists():
            continue
        for item in sorted(skills_dir.iterdir()):
            if item.is_dir() and item.name not in seen:
                skill = Skill.from_path(item)
                if skill:
                    seen.add(item.name)
                    skills.append(skill)
    return skills


def resolve_skill_dir(skill_name: str, search_dirs: list[Path] | None = None) -> Path | None:
    """Return the directory of a skill, searching the profile then _shared. None if absent."""
    if search_dirs is None:
        from common.core.paths import get_skills_search_dirs

        search_dirs = get_skills_search_dirs()
    for skills_dir in search_dirs:
        candidate = skills_dir / skill_name
        if candidate.is_dir():
            return candidate
    return None


def is_shared_skill(skill_path: Path) -> bool:
    """True if skill_path resolves under the _shared base rather than the active profile."""
    from common.core.paths import get_skills_dir

    try:
        skill_path.resolve().relative_to(get_skills_dir().resolve())
        return False
    except ValueError:
        return True
