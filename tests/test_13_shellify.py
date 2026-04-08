"""Tests for the 'skill plan shellify' command."""
from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch


def _get_shellify_module():
    """Import the run-plan register module (hyphenated name)."""
    return importlib.import_module("commands.run-plan.register")


class TestShellifyPrompt:
    """Test the shellify prompt template."""

    def test_shellify_prompt_exists(self):
        """The SHELLIFY_PROMPT_DEFAULT should be defined in the subcommand module."""
        mod = _get_shellify_module()
        assert hasattr(mod, "SHELLIFY_PROMPT_DEFAULT")
        assert isinstance(mod.SHELLIFY_PROMPT_DEFAULT, str)
        assert len(mod.SHELLIFY_PROMPT_DEFAULT) > 100

    def test_shellify_prompt_has_placeholders(self):
        """The prompt should have all required placeholders."""
        mod = _get_shellify_module()
        for key in ["{skill_description}", "{skill_parameters}", "{skill_body}", "{learn_section}",
                     "{existing_script_section}", "{instructions_section}", "{reset_mode}"]:
            assert key in mod.SHELLIFY_PROMPT_DEFAULT


class TestShellifyCommand:
    """Test the shellify CLI command logic."""

    def test_shellify_uses_agent_call(self, skills_dir):
        """shellify should use agent_call() with tool access."""
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        with patch("common.agent.call.agent_call") as mock_agent_call:
            mock_session = MagicMock()
            mock_session.turns = []
            mock_agent_call.return_value = mock_session

            skill = Skill.from_path(skills_dir / "test-echo")
            assert skill is not None

            # Create scripts dir so run.sh path exists
            scripts_dir = skill.path / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            run_sh = scripts_dir / "run.sh"
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
            mock_agent_call.assert_called_once()
            call_kwargs = mock_agent_call.call_args[1]
            assert call_kwargs["workdir"] == skill.path
            assert call_kwargs["max_iterations"] == 5
            assert "task_description" in call_kwargs

    def test_shellify_resets_existing(self, skills_dir):
        """shellify with reset=True should tell agent to start fresh."""
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        with patch("common.agent.call.agent_call") as mock_agent_call:
            mock_session = MagicMock()
            mock_session.turns = []
            mock_agent_call.return_value = mock_session

            skill = Skill.from_path(skills_dir / "test-echo")
            scripts_dir = skill.path / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            run_sh = scripts_dir / "run.sh"
            run_sh.write_text("#!/usr/bin/env bash\nold script\n", encoding="utf-8")

            shellify_mod._shellify_skill(
                skill=skill,
                provider="test-provider",
                reset=True,
                verbose=False,
                max_iterations=5,
            )

            call_kwargs = mock_agent_call.call_args[1]
            task_desc = call_kwargs["task_description"]
            assert "--reset flag" in task_desc or "resetting" in task_desc

    def test_shellify_passes_instruction(self, skills_dir):
        """shellify should include user instruction in the prompt."""
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        with patch("common.agent.call.agent_call") as mock_agent_call:
            mock_session = MagicMock()
            mock_session.turns = []
            mock_agent_call.return_value = mock_session

            skill = Skill.from_path(skills_dir / "test-echo")
            scripts_dir = skill.path / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)

            shellify_mod._shellify_skill(
                skill=skill,
                provider="test-provider",
                instruction="Use curl with retries",
                reset=False,
                verbose=False,
                max_iterations=5,
            )

            call_kwargs = mock_agent_call.call_args[1]
            task_desc = call_kwargs["task_description"]
            assert "Use curl with retries" in task_desc

    def test_shellify_includes_existing_script_as_context(self, skills_dir):
        """shellify should include existing run.sh in the prompt when not resetting."""
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        with patch("common.agent.call.agent_call") as mock_agent_call:
            mock_session = MagicMock()
            mock_session.turns = []
            mock_agent_call.return_value = mock_session

            skill = Skill.from_path(skills_dir / "test-echo")
            scripts_dir = skill.path / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            run_sh = scripts_dir / "run.sh"
            run_sh.write_text("#!/usr/bin/env bash\necho 'existing'\n", encoding="utf-8")

            shellify_mod._shellify_skill(
                skill=skill,
                provider="test-provider",
                reset=False,
                verbose=False,
                max_iterations=5,
            )

            call_kwargs = mock_agent_call.call_args[1]
            task_desc = call_kwargs["task_description"]
            assert "existing scripts/run.sh" in task_desc.lower() or "current version" in task_desc.lower()
