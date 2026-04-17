"""Unit tests for skill exec command functionality."""

import pytest
import yaml
from pathlib import Path
from click.testing import CliRunner
import sys

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR))


@pytest.fixture
def restore_workdir(isolate_xdg):
    """Restore workdir to default after test completes."""
    from common.core.config import load_common_config, save_common_config

    config = load_common_config()
    original_workdir = config.get("workdir")
    yield
    if original_workdir is not None:
        config["workdir"] = original_workdir
        save_common_config(config)
    # If original was None, do nothing - don't remove workdir from config


def get_cli():
    """Get the CLI main group."""
    repo_root = Path(__file__).resolve().parents[1]
    skill_cli_path = str(repo_root / "skill-cli")
    if skill_cli_path in sys.path:
        sys.path.remove(skill_cli_path)
    sys.path.insert(0, skill_cli_path)
    sys.modules.pop("commands", None)
    sys.modules.pop("commands.exec", None)
    sys.modules.pop("commands.exec.register", None)
    from skill_entry import main

    return main


class TestSkillExecCommand:
    """Test skill exec command."""

    def test_exec_command_help(self):
        """Test that exec command is registered and has help."""
        runner = CliRunner()
        result = runner.invoke(get_cli(), ["exec", "--help"])
        assert result.exit_code == 0
        assert "Execute a skill plan from a YAML file" in result.output

    def test_exec_command_requires_plan_file(self):
        """Test that exec command requires a plan file argument."""
        runner = CliRunner()
        result = runner.invoke(get_cli(), ["exec"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output or "PLAN" in result.output

    def test_exec_command_plan_file_not_found(self, tmp_path):
        """Test that exec command fails when plan file doesn't exist."""
        runner = CliRunner()
        non_existent = str(tmp_path / "nonexistent.yaml")
        result = runner.invoke(
            get_cli(), ["exec", non_existent, "--workdir", str(tmp_path)]
        )
        assert result.exit_code != 0
        # The RunPlanFileType.convert will fail before the command runs
        assert "Plan file not found" in result.output or "No such file" in result.output

    def test_exec_command_invalid_plan_file(self, tmp_path):
        """Test that exec command validates plan file format."""
        plan_file = tmp_path / "invalid.yaml"
        plan_file.write_text("not: a: valid: yaml:")

        runner = CliRunner()
        result = runner.invoke(
            get_cli(),
            [
                "exec",
                str(plan_file),
                "--workdir",
                str(tmp_path),
                "--max-iterations",
                "1",
            ],
        )
        # Should fail due to missing LLM config or invalid plan
        assert result.exit_code != 0

    def test_exec_command_missing_goal_in_plan(self, tmp_path):
        """Test that exec command fails when plan is missing goal."""
        plan_file = tmp_path / "no-goal.yaml"
        plan_content = {"plan": [{"step": 1, "action": "task", "description": "Test"}]}
        plan_file.write_text(yaml.dump(plan_content, default_flow_style=False))

        runner = CliRunner()
        result = runner.invoke(
            get_cli(),
            [
                "exec",
                str(plan_file),
                "--workdir",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0
        assert (
            "missing 'goal'" in result.output.lower()
            or "error" in result.output.lower()
        )

    def test_exec_command_with_params(self, tmp_path):
        """Test that exec command accepts -p parameters."""
        plan_file = tmp_path / "plan.yaml"
        plan_content = """
goal: Test {{name}}
params:
  - name
  - message:hello
plan:
  - step: 1
    action: task
    description: "Do something"
"""
        plan_file.write_text(plan_content)

        runner = CliRunner()
        result = runner.invoke(
            get_cli(),
            [
                "exec",
                str(plan_file),
                "--workdir",
                str(tmp_path),
                "-p",
                "name=test",
            ],
        )
        # Will fail due to missing LLM, but should accept the params
        assert "Plan file not found" not in result.output
        assert "missing 'goal'" not in result.output.lower()

    def test_exec_command_with_all_flags(self, tmp_path, restore_workdir):
        """Test that exec command accepts all inherited flags."""
        plan_file = tmp_path / "plan.yaml"
        plan_content = {"goal": "Test", "plan": []}
        plan_file.write_text(yaml.dump(plan_content, default_flow_style=False))

        runner = CliRunner()
        result = runner.invoke(
            get_cli(),
            [
                "exec",
                str(plan_file),
                "--workdir",
                str(tmp_path),
                "--provider",
                "test",
                "--model",
                "test-model",
                "--max-iterations",
                "5",
                "--verbose",
                "--retry-limit",
                "3",
                "--auto-learn",
                "--compact",
                "--no-ask",
                "--no-eval",
                "--save-session",
                "--run-isolated",
                "--skill-isolated",
                "--shared-context",
                "--interactive",
            ],
        )
        # Will fail due to invalid provider/LLM, but flags should be accepted
        # The error should be about provider, not about invalid flags
        assert "no such option" not in result.output.lower()
        assert "invalid option" not in result.output.lower()


class TestSkillExecPlanImport:
    """Test that skill exec correctly imports and validates plans."""

    def test_exec_import_valid_plan_with_run_step(self, tmp_path):
        """Test exec imports a valid plan with run steps."""
        from core.plan_utils import import_plan_from_yaml

        plan_file = tmp_path / "plan.yaml"
        plan_content = {
            "goal": "Test goal",
            "success_criteria": "Test criteria",
            "plan": [
                {
                    "step": 1,
                    "action": "run",
                    "skill": "test-skill",
                }
            ],
        }
        plan_file.write_text(yaml.dump(plan_content, default_flow_style=False))

        plan = import_plan_from_yaml(str(plan_file))

        assert plan.goal == "Test goal"
        assert plan.success_criteria == "Test criteria"
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "run"
        assert plan.steps[0].skill_name == "test-skill"
        # Params are now empty on the step (global params injected at runtime)
        assert plan.steps[0].params == {}

    def test_exec_import_valid_plan_with_task_step(self, tmp_path):
        """Test exec imports a valid plan with task steps."""
        from core.plan_utils import import_plan_from_yaml

        plan_file = tmp_path / "plan.yaml"
        plan_content = {
            "goal": "Test goal",
            "plan": [
                {
                    "step": 1,
                    "action": "task",
                    "description": "Do something",
                    "instructions": "Instructions here",
                }
            ],
        }
        plan_file.write_text(yaml.dump(plan_content, default_flow_style=False))

        plan = import_plan_from_yaml(str(plan_file))

        assert len(plan.steps) == 1
        assert plan.steps[0].action == "task"
        assert plan.steps[0].description == "Do something"
        assert plan.steps[0].instructions == "Instructions here"

    def test_exec_import_plan_with_placeholders(self, tmp_path):
        """Test exec imports plan with {{key}} placeholders and substitutes them."""
        from core.plan_utils import import_plan_from_yaml

        plan_file = tmp_path / "plan.yaml"
        plan_content = """
goal: Process {{INPUT_FILE}}
params:
  - INPUT_FILE:data.csv
plan:
  - step: 1
    action: task
    description: "Work on file"
"""
        plan_file.write_text(plan_content)

        plan = import_plan_from_yaml(str(plan_file))

        assert plan.goal == "Process data.csv"

    def test_exec_import_plan_with_default_placeholders(self, tmp_path):
        """Test exec imports plan with {{key:default}} placeholders."""
        from core.plan_utils import import_plan_from_yaml

        plan_file = tmp_path / "plan.yaml"
        plan_content = """
goal: Process {{INPUT_FILE:input.csv}}
params:
  - INPUT_FILE:input.csv
plan:
  - step: 1
    action: task
    description: "Work on file"
"""
        plan_file.write_text(plan_content)

        # Without providing the param, should use default
        plan = import_plan_from_yaml(str(plan_file))

        assert plan.goal == "Process input.csv"

        # With param override, should use provided value
        plan2 = import_plan_from_yaml(
            str(plan_file), params={"INPUT_FILE": "custom.csv"}
        )
        assert plan2.goal == "Process custom.csv"

    def test_exec_import_plan_unresolved_placeholders_fails(self, tmp_path):
        """Test exec fails when mandatory placeholders are not resolved."""
        from core.plan_utils import import_plan_from_yaml

        plan_file = tmp_path / "plan.yaml"
        plan_content = """
goal: Process {{REQUIRED_PARAM}}
params:
  - REQUIRED_PARAM
plan: []
"""
        plan_file.write_text(plan_content)

        with pytest.raises(ValueError, match="Missing required plan parameters"):
            import_plan_from_yaml(str(plan_file))

    def test_exec_import_plan_with_global_params(self, tmp_path):
        """Test exec imports plan with global params section."""
        from core.plan_utils import import_plan_from_yaml

        plan_file = tmp_path / "plan.yaml"
        plan_content = """
goal: Process {{URL}}
params:
  - URL
  - LANGUAGE:fr
  - MAX_RESULTS:50
plan:
  - step: 1
    action: run
    skill: test-skill
  - step: 2
    action: run
    skill: another-skill
"""
        plan_file.write_text(plan_content)

        # Without providing URL, should fail
        with pytest.raises(ValueError, match="Missing required plan parameters"):
            import_plan_from_yaml(str(plan_file))

        # With URL provided, should succeed
        plan = import_plan_from_yaml(
            str(plan_file), params={"URL": "https://example.com"}
        )
        assert plan.goal == "Process https://example.com"
        assert len(plan.steps) == 2
        assert plan.steps[0].skill_name == "test-skill"
        assert plan.steps[1].skill_name == "another-skill"
        # Steps don't have params (global params injected at runtime)
        assert plan.steps[0].params == {}
        assert plan.steps[1].params == {}


class TestSkillExecVsRun:
    """Test the distinction between skill exec and skill run."""

    def test_exec_requires_plan_file(self):
        """Test that skill exec requires a plan file argument."""
        runner = CliRunner()
        result = runner.invoke(get_cli(), ["exec"])
        assert result.exit_code != 0
        # Should complain about missing PLAN argument
        assert "Missing argument" in result.output or "PLAN" in result.output

    def test_run_does_not_accept_import_flag(self):
        """Test that skill run no longer accepts --import flag."""
        runner = CliRunner()
        result = runner.invoke(
            get_cli(),
            [
                "run",
                "test task",
                "--import",
                "plan.yaml",
            ],
        )
        # Should fail because --import is not a valid option anymore
        assert result.exit_code != 0
        assert (
            "no such option" in result.output.lower()
            or "error" in result.output.lower()
        )

    def test_run_accepts_param_flag(self):
        """Test that skill run now accepts --param/-p flag (matching skill exec)."""
        runner = CliRunner()
        result = runner.invoke(
            get_cli(),
            [
                "run",
                "test task",
                "-p",
                "key=value",
            ],
        )
        # Should not fail with "no such option" - param flag is now supported
        # It may fail for other reasons (no LLM, missing skills, etc.) but not due to invalid option
        assert (
            "no such option" not in result.output.lower()
            or "-p" not in result.output.lower()
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
