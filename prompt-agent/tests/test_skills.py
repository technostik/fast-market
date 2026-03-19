from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def temp_skills_dir(tmp_path, monkeypatch):
    """Create a temporary skills directory."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    monkeypatch.setattr("common.core.paths.get_skills_dir", lambda: skills_dir)
    monkeypatch.setattr("commands.skill.register.get_skills_dir", lambda: skills_dir)
    return skills_dir


@pytest.fixture
def runner():
    from click.testing import CliRunner

    return CliRunner()


class TestSkillModel:
    """Tests for the Skill model and discovery functions."""

    def test_skill_from_path_no_skill_file(self, tmp_path):
        """Test loading from directory without SKILL.md."""
        from core.skill import Skill

        skill_dir = tmp_path / "no-skill"
        skill_dir.mkdir()
        skill = Skill.from_path(skill_dir)
        assert skill is None

    def test_skill_from_path_with_skill_file(self, tmp_path):
        """Test loading from directory with SKILL.md."""
        from core.skill import Skill

        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            """---
name: my-skill
description: A test skill
---

# My Skill
Content here.
""",
            encoding="utf-8",
        )

        skill = Skill.from_path(skill_dir)
        assert skill is not None
        assert skill.name == "my-skill"
        assert skill.description == "A test skill"
        assert skill.has_scripts is False

    def test_skill_from_path_with_scripts(self, tmp_path):
        """Test loading skill with scripts directory."""
        from core.skill import Skill

        skill_dir = tmp_path / "with-scripts"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: scripts-skill
description: Has scripts
---

# Scripts Skill
""",
            encoding="utf-8",
        )
        (skill_dir / "scripts").mkdir()

        skill = Skill.from_path(skill_dir)
        assert skill is not None
        assert skill.has_scripts is True

    def test_skill_from_path_no_frontmatter(self, tmp_path):
        """Test loading skill without YAML frontmatter."""
        from core.skill import Skill

        skill_dir = tmp_path / "plain-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Plain Skill\nNo frontmatter", encoding="utf-8"
        )

        skill = Skill.from_path(skill_dir)
        assert skill is not None
        assert skill.name == "plain-skill"
        assert skill.description == ""

    def test_discover_skills_empty_dir(self, tmp_path):
        """Test discovering skills in empty directory."""
        from core.skill import discover_skills

        skills = discover_skills(tmp_path)
        assert skills == []

    def test_discover_skills_nonexistent_dir(self):
        """Test discovering skills in non-existent directory."""
        from core.skill import discover_skills

        skills = discover_skills(Path("/nonexistent/skills"))
        assert skills == []

    def test_discover_skills_with_multiple(self, tmp_path):
        """Test discovering multiple skills."""
        from core.skill import Skill, discover_skills

        skill1 = tmp_path / "skill-a"
        skill1.mkdir()
        (skill1 / "SKILL.md").write_text(
            "---\nname: skill-a\n---\n# A", encoding="utf-8"
        )

        skill2 = tmp_path / "skill-b"
        skill2.mkdir()
        (skill2 / "SKILL.md").write_text(
            "---\nname: skill-b\n---\n# B", encoding="utf-8"
        )

        (tmp_path / "not-a-skill").mkdir()

        skills = discover_skills(tmp_path)
        assert len(skills) == 2
        assert skills[0].name == "skill-a"
        assert skills[1].name == "skill-b"

    def test_discover_skills_sorted(self, tmp_path):
        """Test that skills are sorted alphabetically."""
        from core.skill import discover_skills

        for name in ["zebra", "apple", "mango"]:
            skill_dir = tmp_path / name
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\n---\n# {name}", encoding="utf-8"
            )

        skills = discover_skills(tmp_path)
        assert [s.name for s in skills] == ["apple", "mango", "zebra"]


class TestSkillCommands:
    """Tests for the skill CLI command."""

    def test_skill_list_empty(self, runner, temp_skills_dir):
        """Test listing skills when none exist."""
        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["list"])

        assert result.exit_code == 0
        assert "No skills found" in result.output

    def test_skill_list(self, runner, temp_skills_dir):
        """Test listing skills."""
        skill_dir = temp_skills_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: A test skill\n---\n# Test",
            encoding="utf-8",
        )

        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["list"])

        assert result.exit_code == 0
        assert "test-skill" in result.output
        assert "A test skill" in result.output

    def test_skill_list_json(self, runner, temp_skills_dir):
        """Test listing skills in JSON format."""
        skill_dir = temp_skills_dir / "json-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: json-skill\ndescription: JSON test\n---\n# JSON",
            encoding="utf-8",
        )

        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["list", "--format", "json"])

        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["name"] == "json-skill"

    def test_skill_path(self, runner, temp_skills_dir):
        """Test showing skills directory path."""
        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["path"])

        assert result.exit_code == 0
        assert str(temp_skills_dir) in result.output

    def test_skill_create(self, runner, temp_skills_dir):
        """Test creating a skill."""
        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(
            manifest.click_command,
            ["create", "new-skill", "-d", "A new skill"],
        )

        assert result.exit_code == 0
        assert "Created skill: new-skill" in result.output

        skill_path = temp_skills_dir / "new-skill"
        assert skill_path.exists()
        assert (skill_path / "SKILL.md").exists()

        content = (skill_path / "SKILL.md").read_text(encoding="utf-8")
        assert "name: new-skill" in content
        assert "A new skill" in content

    def test_skill_create_with_scripts(self, runner, temp_skills_dir):
        """Test creating a skill with scripts directory."""
        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(
            manifest.click_command,
            ["create", "script-skill", "--with-scripts"],
        )

        assert result.exit_code == 0
        skill_path = temp_skills_dir / "script-skill"
        assert (skill_path / "scripts").exists()
        assert (skill_path / "scripts" / "README.md").exists()

    def test_skill_create_duplicate(self, runner, temp_skills_dir):
        """Test creating a skill that already exists."""
        from commands.skill.register import register

        (temp_skills_dir / "existing").mkdir()

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["create", "existing"])

        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_skill_show(self, runner, temp_skills_dir):
        """Test showing skill details."""
        skill_dir = temp_skills_dir / "show-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: show-skill\ndescription: Show test\n---\n# Show Skill\nContent here.",
            encoding="utf-8",
        )

        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["show", "show-skill"])

        assert result.exit_code == 0
        assert "show-skill" in result.output
        assert "Show test" in result.output

    def test_skill_show_with_scripts(self, runner, temp_skills_dir):
        """Test showing skill with scripts."""
        skill_dir = temp_skills_dir / "script-show"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: script-show\n---\n# Script Show", encoding="utf-8"
        )
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.sh").write_text("#!/bin/bash\necho hello", encoding="utf-8")

        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["show", "script-show"])

        assert result.exit_code == 0
        assert "run.sh" in result.output

    def test_skill_show_nonexistent(self, runner, temp_skills_dir):
        """Test showing a non-existent skill."""
        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["show", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_skill_delete(self, runner, temp_skills_dir):
        """Test deleting a skill with confirmation."""
        skill_dir = temp_skills_dir / "delete-me"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\n---\n# Delete", encoding="utf-8")

        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(
            manifest.click_command, ["delete", "delete-me"], input="y\n"
        )

        assert result.exit_code == 0
        assert not skill_dir.exists()

    def test_skill_delete_force(self, runner, temp_skills_dir):
        """Test deleting a skill with --force."""
        skill_dir = temp_skills_dir / "force-delete"
        skill_dir.mkdir()

        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(
            manifest.click_command, ["delete", "force-delete", "--force"]
        )

        assert result.exit_code == 0
        assert not skill_dir.exists()

    def test_skill_delete_nonexistent(self, runner, temp_skills_dir):
        """Test deleting a non-existent skill."""
        from commands.skill.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["delete", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output


class TestSkillExecution:
    """Tests for skill execution in task executor."""

    def test_execute_skill_command(self, temp_skills_dir):
        """Test executing a skill script."""
        skill_dir = temp_skills_dir / "test-exec"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-exec\ndescription: Test execution\n---\n# Test",
            encoding="utf-8",
        )
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        script = scripts_dir / "hello.sh"
        script.write_text("#!/bin/bash\necho 'Hello from skill'", encoding="utf-8")
        script.chmod(0o755)

        from commands.task.executor import resolve_and_execute_command
        from pathlib import Path

        result = resolve_and_execute_command(
            "skill:test-exec/hello.sh",
            Path("/tmp"),
            set(),
            60,
        )

        assert result.exit_code == 0
        assert "Hello from skill" in result.stdout

    def test_execute_skill_command_with_args(self, temp_skills_dir):
        """Test executing a skill script with arguments."""
        skill_dir = temp_skills_dir / "args-test"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: args-test\n---\n# Args", encoding="utf-8"
        )
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        script = scripts_dir / "echo.sh"
        script.write_text('#!/bin/bash\necho "Args: $@"', encoding="utf-8")
        script.chmod(0o755)

        from commands.task.executor import resolve_and_execute_command
        from pathlib import Path

        result = resolve_and_execute_command(
            "skill:args-test/echo.sh hello world",
            Path("/tmp"),
            set(),
            60,
        )

        assert result.exit_code == 0
        assert "hello" in result.stdout
        assert "world" in result.stdout

    def test_execute_skill_command_not_found(self, temp_skills_dir):
        """Test executing a non-existent skill script."""
        from commands.task.executor import resolve_and_execute_command
        from pathlib import Path

        result = resolve_and_execute_command(
            "skill:nonexistent/script.sh",
            Path("/tmp"),
            set(),
            60,
        )

        assert result.exit_code == 1
        assert "not found" in result.stderr.lower()

    def test_execute_skill_command_invalid_format(self, temp_skills_dir):
        """Test executing with invalid skill format."""
        from commands.task.executor import resolve_and_execute_command
        from pathlib import Path

        result = resolve_and_execute_command(
            "skill:no-slash",
            Path("/tmp"),
            set(),
            60,
        )

        assert result.exit_code == 1
        assert "Invalid skill format" in result.stderr

    def test_dry_run_with_skill(self, temp_skills_dir):
        """Test dry-run with skill command."""
        skill_dir = temp_skills_dir / "dry-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: dry-skill\n---\n# Dry", encoding="utf-8"
        )
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.sh").write_text("#!/bin/bash\necho hi", encoding="utf-8")

        from commands.task.executor import execute_dry_run
        from pathlib import Path

        result = execute_dry_run("skill:dry-skill/run.sh", Path("/tmp"), set())

        assert result["would_execute"] is True
        assert "run.sh" in result["resolved_command"]

    def test_dry_run_with_skill_not_found(self, temp_skills_dir):
        """Test dry-run with non-existent skill."""
        from commands.task.executor import execute_dry_run
        from pathlib import Path

        result = execute_dry_run("skill:missing/script.sh", Path("/tmp"), set())

        assert result["would_execute"] is False
        assert "not found" in result["reason"].lower()
