"""Tests for the 'skill plan shellify' command."""
from __future__ import annotations

import importlib
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch


def _get_shellify_module():
    """Import the shellify module (hyphenated name)."""
    return importlib.import_module("commands.run-plan.shellify")


class TestShellifyPrompt:
    """Test the shellify prompt template."""

    def test_shellify_prompt_exists(self):
        """The SHELLIFY_PROMPT_DEFAULT should be defined in the subcommand module."""
        mod = _get_shellify_module()
        assert hasattr(mod, "SHELLIFY_PROMPT_DEFAULT")
        assert isinstance(mod.SHELLIFY_PROMPT_DEFAULT, str)
        assert len(mod.SHELLIFY_PROMPT_DEFAULT) > 100

    def test_shellify_prompt_has_placeholders(self):
        """The agentic prompt should have all required placeholders."""
        mod = _get_shellify_module()
        for key in ["{skill_description}", "{skill_parameters}", "{skill_body}", "{learn_section}",
                     "{existing_script_section}", "{instructions_section}", "{tools_section}", "{reset_mode}"]:
            assert key in mod.SHELLIFY_PROMPT_DEFAULT

    def test_shellify_noagent_prompt_has_placeholders(self):
        """The no-agent prompt should have all required placeholders."""
        mod = _get_shellify_module()
        for key in ["{skill_description}", "{skill_parameters}", "{skill_body}", "{learn_section}", "{tools_section}"]:
            assert key in mod.SHELLIFY_NOAGENT_PROMPT


class TestShellifyCommand:
    """Test the shellify CLI command logic."""

    def test_shellify_uses_agent_call(self, skills_dir):
        """shellify should use agent_call() with tool access."""
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        def _mock_agent_call(*args, **kwargs):
            """Simulate agent writing run.sh."""
            workdir = kwargs.get("workdir")
            run_sh = workdir / "scripts" / "run.sh"
            run_sh.parent.mkdir(parents=True, exist_ok=True)
            run_sh.write_text("#!/usr/bin/env bash\necho test\n", encoding="utf-8")
            mock_session = MagicMock()
            mock_session.turns = []
            return mock_session

        with patch("common.agent.call.agent_call", side_effect=_mock_agent_call):
            skill = Skill.from_path(skills_dir / "test-echo")
            assert skill is not None

            # Create scripts dir and backup if exists
            scripts_dir = skill.path / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            run_sh = scripts_dir / "run.sh"
            
            # Backup existing run.sh if it exists
            backup_path = None
            if run_sh.exists():
                backup_path = run_sh.with_name("run.sh.test.bak")
                shutil.copy2(run_sh, backup_path)

            try:
                run_sh.write_text("#!/usr/bin/env bash\necho test\n", encoding="utf-8")

                result = shellify_mod._shellify_skill(
                    skill=skill,
                    provider="test-provider",
                    model=None,
                    prompt_template=None,
                    instruction=None,
                    reset=False,
                    verbose=False,
                    max_iterations=5,
                )

                assert result is True
                assert run_sh.exists()
            finally:
                # Restore original or delete new file
                if backup_path and backup_path.exists():
                    shutil.copy2(backup_path, run_sh)
                    backup_path.unlink()
                elif run_sh.exists():
                    run_sh.unlink()

    def test_shellify_resets_existing(self, skills_dir):
        """shellify with reset=True should tell agent to start fresh."""
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        captured = {}

        def _mock_agent_call(*args, **kwargs):
            captured["task_description"] = kwargs.get("task_description", "")
            workdir = kwargs.get("workdir")
            run_sh = workdir / "scripts" / "run.sh"
            run_sh.parent.mkdir(parents=True, exist_ok=True)
            run_sh.write_text("#!/usr/bin/env bash\nnew script\n", encoding="utf-8")
            mock_session = MagicMock()
            mock_session.turns = []
            return mock_session

        with patch("common.agent.call.agent_call", side_effect=_mock_agent_call):
            skill = Skill.from_path(skills_dir / "test-echo")
            scripts_dir = skill.path / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            run_sh = scripts_dir / "run.sh"
            
            # Store original content
            original_content = run_sh.read_text(encoding="utf-8") if run_sh.exists() else None

            try:
                run_sh.write_text("#!/usr/bin/env bash\nold script\n", encoding="utf-8")

                shellify_mod._shellify_skill(
                    skill=skill,
                    provider="test-provider",
                    reset=True,
                    verbose=False,
                    max_iterations=5,
                )

                assert "starting fresh" in captured.get("task_description", "").lower()
            finally:
                # Restore original
                if original_content is not None:
                    run_sh.write_text(original_content, encoding="utf-8")
                elif run_sh.exists():
                    run_sh.unlink()

    def test_shellify_passes_instruction(self, skills_dir):
        """shellify should include user instruction in the prompt."""
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        captured = {}

        def _mock_agent_call(*args, **kwargs):
            captured["task_description"] = kwargs.get("task_description", "")
            workdir = kwargs.get("workdir")
            run_sh = workdir / "scripts" / "run.sh"
            run_sh.parent.mkdir(parents=True, exist_ok=True)
            run_sh.write_text("#!/usr/bin/env bash\nscript\n", encoding="utf-8")
            mock_session = MagicMock()
            mock_session.turns = []
            return mock_session

        with patch("common.agent.call.agent_call", side_effect=_mock_agent_call):
            skill = Skill.from_path(skills_dir / "test-echo")
            scripts_dir = skill.path / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            run_sh = scripts_dir / "run.sh"
            
            # Store original content
            original_content = run_sh.read_text(encoding="utf-8") if run_sh.exists() else None

            try:
                shellify_mod._shellify_skill(
                    skill=skill,
                    provider="test-provider",
                    instruction="Use curl with retries",
                    reset=False,
                    verbose=False,
                    max_iterations=5,
                )

                assert "Use curl with retries" in captured.get("task_description", "")
            finally:
                # Restore original
                if original_content is not None:
                    run_sh.write_text(original_content, encoding="utf-8")
                elif run_sh.exists():
                    run_sh.unlink()

    def test_shellify_includes_existing_script_as_context(self, skills_dir):
        """shellify should include existing run.sh in the prompt when not resetting."""
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        captured = {}

        def _mock_agent_call(*args, **kwargs):
            captured["task_description"] = kwargs.get("task_description", "")
            workdir = kwargs.get("workdir")
            run_sh = workdir / "scripts" / "run.sh"
            run_sh.parent.mkdir(parents=True, exist_ok=True)
            run_sh.write_text("#!/usr/bin/env bash\nscript\n", encoding="utf-8")
            mock_session = MagicMock()
            mock_session.turns = []
            return mock_session

        with patch("common.agent.call.agent_call", side_effect=_mock_agent_call):
            skill = Skill.from_path(skills_dir / "test-echo")
            scripts_dir = skill.path / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            run_sh = scripts_dir / "run.sh"
            
            # Store original content
            original_content = run_sh.read_text(encoding="utf-8") if run_sh.exists() else None

            try:
                run_sh.write_text("#!/usr/bin/env bash\necho 'existing'\n", encoding="utf-8")

                shellify_mod._shellify_skill(
                    skill=skill,
                    provider="test-provider",
                    reset=False,
                    verbose=False,
                    max_iterations=5,
                )

                task_desc = captured.get("task_description", "")
                assert "existing scripts/run.sh" in task_desc.lower() or "current version" in task_desc.lower()
            finally:
                # Restore original
                if original_content is not None:
                    run_sh.write_text(original_content, encoding="utf-8")
                elif run_sh.exists():
                    run_sh.unlink()
