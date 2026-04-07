from __future__ import annotations

from pathlib import Path

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


class SessionFileType(click.ParamType):
    name = "SESSION_FILE"

    def shell_complete(self, ctx, param, incomplete):
        from pathlib import Path

        try:
            workdir = ctx.params.get("workdir") if ctx else None
            if workdir:
                cwd = Path(workdir)
            else:
                try:
                    from common.core.config import load_common_config

                    common_config = load_common_config()
                    workdir_path = common_config.get("workdir")
                    cwd = (
                        Path(workdir_path).expanduser().resolve()
                        if workdir_path
                        else Path.cwd()
                    )
                except Exception:
                    cwd = Path.cwd()
        except Exception:
            try:
                from common.core.config import load_common_config

                common_config = load_common_config()
                workdir_path = common_config.get("workdir")
                cwd = (
                    Path(workdir_path).expanduser().resolve()
                    if workdir_path
                    else Path.cwd()
                )
            except Exception:
                cwd = Path.cwd()

        if not cwd.exists() or not cwd.is_dir():
            return []

        items = []
        search_in = incomplete

        ends_with_slash = search_in.endswith("/")

        if not ends_with_slash and "/" not in search_in:
            search_patterns = ["*.yaml", "*.session.yaml"]
            for pattern in search_patterns:
                for path in cwd.glob(pattern):
                    if path.is_file() and not path.name.startswith("."):
                        try:
                            rel = path.relative_to(cwd)
                        except Exception:
                            continue
                        if rel.as_posix().startswith(search_in):
                            items.append(CompletionItem(rel.as_posix()))

            for path in sorted(cwd.iterdir()):
                if path.is_dir() and not path.name.startswith("."):
                    if path.name.startswith(search_in):
                        items.append(CompletionItem(path.name + "/", help="Directory"))
        else:
            if ends_with_slash:
                search_in = search_in[:-1]

            search_dir = cwd / search_in
            if search_dir.is_dir():
                for path in sorted(search_dir.iterdir()):
                    if path.name.startswith("."):
                        continue
                    if path.is_file():
                        if path.name.endswith(".yaml") or path.name.endswith(
                            ".session.yaml"
                        ):
                            items.append(CompletionItem(incomplete + path.name))
                    elif path.is_dir():
                        items.append(
                            CompletionItem(
                                incomplete + path.name + "/", help="Directory"
                            )
                        )
            elif "/" in search_in:
                base_path = search_in.rsplit("/", 1)[0]
                prefix = base_path + "/"
                search_prefix = search_in.split("/")[-1]
                search_dir = cwd / base_path
                if search_dir.is_dir():
                    for path in sorted(search_dir.iterdir()):
                        if path.name.startswith("."):
                            continue
                        if path.is_dir():
                            if path.name.startswith(search_prefix):
                                items.append(
                                    CompletionItem(
                                        prefix + path.name + "/", help="Directory"
                                    )
                                )
                        elif path.is_file():
                            if path.name.endswith(".yaml") or path.name.endswith(
                                ".session.yaml"
                            ):
                                if path.name.startswith(search_prefix):
                                    items.append(CompletionItem(prefix + path.name))

        return sorted(items, key=lambda x: x.name or "")

    def convert(self, value, param, ctx):
        return value


class RunPlanFileType(click.ParamType):
    name = "RUN_PLAN"

    def _get_workdir(self):
        """Get the workdir from common config or fallback to cwd."""
        try:
            from common.core.config import load_common_config
            common_config = load_common_config()
            workdir_path = common_config.get("workdir")
            return (
                Path(workdir_path).expanduser().resolve()
                if workdir_path
                else Path.cwd()
            )
        except Exception:
            return Path.cwd()

    def _find_run_plans(self, workdir: Path):
        """Find all run.yaml/run.yml files recursively."""
        plans = []
        for pattern in ["run.yaml", "run.yml"]:
            plans.extend(workdir.rglob(pattern))
        return sorted(set(plans))

    def shell_complete(self, ctx, param, incomplete):
        cwd = self._get_workdir()
        if not cwd.exists() or not cwd.is_dir():
            return []

        plans = self._find_run_plans(cwd)
        items = []

        for plan_path in plans:
            try:
                rel = plan_path.relative_to(cwd).as_posix()
            except ValueError:
                rel = str(plan_path)

            if not rel.startswith(incomplete):
                continue

            # Try to read goal for help text
            help_text = ""
            try:
                import yaml
                data = yaml.safe_load(plan_path.read_text())
                if isinstance(data, dict) and data.get("goal"):
                    help_text = data["goal"]
            except Exception:
                pass

            items.append(CompletionItem(rel, help=help_text))

        return items

    def convert(self, value, param, ctx):
        # If it's a relative path, resolve against workdir
        path = Path(value)
        if not path.is_absolute():
            workdir = self._get_workdir()
            path = workdir / path
        return path.resolve()
