from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass(slots=True)
class Skill:
    """Represents a skill folder following Anthropic's skill format."""

    name: str
    path: Path
    description: str = ""
    has_scripts: bool = False
    parameters: list[dict] = field(default_factory=list)
    run: str = ""

    @classmethod
    def from_path(cls, path: Path) -> Optional[Skill]:
        """Load skill from directory if valid."""
        skill_file = path / "SKILL.md"
        if not skill_file.exists():
            return None

        content = skill_file.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1])
                    return cls(
                        name=frontmatter.get("name", path.name),
                        path=path,
                        description=frontmatter.get("description", ""),
                        has_scripts=(path / "scripts").exists(),
                        parameters=frontmatter.get("parameters", []),
                        run=frontmatter.get("run", ""),
                    )
                except Exception:
                    pass

        return cls(name=path.name, path=path, description="")

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
