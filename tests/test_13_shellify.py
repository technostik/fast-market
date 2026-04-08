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
        for key in ["{skill_description}", "{skill_parameters}", "{skill_body}", "{learn_section}"]:
            assert key in mod.SHELLIFY_PROMPT_DEFAULT


class TestShellifyCommand:
    """Test the shellify CLI command logic."""

    def test_shellify_generates_script(self, skills_dir, tmp_path):
        """shellify should call LLM and write scripts/run.sh."""
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        # Create a mock LLM response
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = """#!/usr/bin/env bash
set -euo pipefail

echo "Hello from shellified skill"
"""
        mock_llm.complete.return_value = mock_response

        # Get a test skill
        skill = Skill.from_path(skills_dir / "test-echo")
        assert skill is not None

        # Call the shellify function
        result = shellify_mod._shellify_skill(
            skill=skill,
            llm=mock_llm,
            model=None,
            prompt=None,  # use default
        )

        assert result is True
        script_path = skill.path / "scripts" / "run.sh"
        assert script_path.exists()
        content = script_path.read_text()
        assert "#!/usr/bin/env bash" in content
        assert "set -euo pipefail" in content

    def test_shellify_strips_markdown_fences(self, skills_dir):
        """shellify should strip markdown code fences from LLM output."""
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = """```bash
#!/usr/bin/env bash
set -euo pipefail
echo "stripped"
```
"""
        mock_llm.complete.return_value = mock_response

        skill = Skill.from_path(skills_dir / "test-echo")
        result = shellify_mod._shellify_skill(
            skill=skill,
            llm=mock_llm,
            model=None,
            prompt=None,
        )

        assert result is True
        script_path = skill.path / "scripts" / "run.sh"
        content = script_path.read_text()
        assert "```" not in content
        assert "#!/usr/bin/env bash" in content

    def test_shellify_makes_script_executable(self, skills_dir):
        """shellify should make run.sh executable."""
        import os
        from core.skill import Skill

        shellify_mod = _get_shellify_module()

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "#!/usr/bin/env bash\necho test\n"
        mock_llm.complete.return_value = mock_response

        skill = Skill.from_path(skills_dir / "test-echo")
        shellify_mod._shellify_skill(skill=skill, llm=mock_llm, model=None, prompt=None)

        script_path = skill.path / "scripts" / "run.sh"
        assert os.access(script_path, os.X_OK)
