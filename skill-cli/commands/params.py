from __future__ import annotations

import click
from click.shell_completion import CompletionItem

from common.core.paths import get_skills_dir
from core.skill import Skill, discover_skills


class SkillRefType(click.ParamType):
    name = "SKILL_REF"

    def shell_complete(self, ctx, param, incomplete):
        try:
            skills_dir = get_skills_dir()
            skills = discover_skills(skills_dir)
        except Exception:
            return []

        items = []
        for skill in skills:
            if skill.name.startswith(incomplete):
                items.append(CompletionItem(skill.name, help=skill.description or ""))

            if "/" in incomplete and incomplete.startswith(skill.name + "/"):
                script_prefix = incomplete[len(skill.name) + 1 :]
                if skill.has_scripts:
                    scripts_dir = skill.path / "scripts"
                    if not scripts_dir.exists():
                        continue
                    for script in sorted(scripts_dir.iterdir()):
                        if script.is_file() and not script.name.startswith("."):
                            if script.name.startswith(script_prefix):
                                items.append(
                                    CompletionItem(
                                        f"{skill.name}/{script.name}",
                                        help=f"Script in {skill.name}",
                                    )
                                )
        return items

    def convert(self, value, param, ctx):
        return value


class SkillNameType(click.ParamType):
    name = "SKILL_NAME"

    def shell_complete(self, ctx, param, incomplete):
        try:
            skills = discover_skills(get_skills_dir())
        except Exception:
            return []

        return [
            CompletionItem(skill.name, help=skill.description or "")
            for skill in skills
            if skill.name.startswith(incomplete)
        ]

    def convert(self, value, param, ctx):
        return value


class SkillFileType(click.ParamType):
    name = "FILE"

    def shell_complete(self, ctx, param, incomplete):
        skill_name = ctx.params.get("skill_name", "")
        if not skill_name:
            return []

        try:
            skill_dir = (get_skills_dir() / str(skill_name)).resolve()
        except Exception:
            return []

        if not skill_dir.exists() or not skill_dir.is_dir():
            return []

        items = []
        for path in sorted(skill_dir.rglob("*")):
            if path.name.startswith(".") or path.is_dir():
                continue
            try:
                rel = path.relative_to(skill_dir).as_posix()
            except Exception:
                continue
            if rel.startswith(incomplete):
                items.append(CompletionItem(rel))
        return items

    def convert(self, value, param, ctx):
        return value


class SkillParamType(click.ParamType):
    name = "KEY=VALUE"

    def shell_complete(self, ctx, param, incomplete):
        skill_ref = ctx.params.get("skill_ref", "")
        if not skill_ref:
            return []

        try:
            skill_name = str(skill_ref).split("/", 1)[0]
            skill_path = get_skills_dir() / skill_name
            skill = Skill.from_path(skill_path)
        except Exception:
            return []

        if not skill or not skill.parameters:
            return []

        already = set()
        for val in ctx.params.get("params") or []:
            if "=" in val:
                already.add(val.split("=")[0])

        required_items = []
        optional_items = []
        for p in skill.parameters:
            name = p.get("name")
            if not name or name in already:
                continue
            key = f"{name}="
            if not key.startswith(incomplete):
                continue
            desc = p.get("description", "")
            if p.get("required", False):
                desc = f"[required] {desc}".strip()
                required_items.append(CompletionItem(key, help=desc))
            else:
                optional_items.append(CompletionItem(key, help=desc))

        return required_items + optional_items

    def convert(self, value, param, ctx):
        return value
