"""Unit tests for export/import YAML functionality - no LLM required."""
import pytest
import yaml
from pathlib import Path
import tempfile

from core.router import (
    _import_plan_from_yaml,
    _plan_to_yaml,
    _execution_log_to_yaml,
    _export_plan_to_file,
    _export_execution_log,
    SkillPlan,
    SkillPlanStep,
    SkillExecutionLog,
    RouterState,
    SkillAttempt,
)


class TestPlanImportExport:
    """Test plan import and export functionality."""

    def test_import_valid_plan(self, tmp_path):
        """Import a valid YAML plan file."""
        plan_file = tmp_path / "plan.yaml"
        plan_content = {
            "goal": "Test goal",
            "success_criteria": "Test criteria",
            "preparation_plan": "Test preparation",
            "plan": [
                {
                    "step": 1,
                    "action": "run",
                    "skill": "test-skill",
                    "params": {"input": "test"},
                    "inject": "Inject this",
                },
                {
                    "step": 2,
                    "action": "task",
                    "description": "Do something",
                },
            ],
        }
        plan_file.write_text(yaml.dump(plan_content, default_flow_style=False))

        plan = _import_plan_from_yaml(str(plan_file))

        assert plan.goal == "Test goal"
        assert plan.success_criteria == "Test criteria"
        assert len(plan.steps) == 2
        assert plan.steps[0].action == "run"
        assert plan.steps[0].skill_name == "test-skill"
        assert plan.steps[0].inject == "Inject this"
        assert plan.steps[1].action == "task"

    def test_import_plan_missing_goal(self, tmp_path):
        """Import fails when goal is missing."""
        plan_file = tmp_path / "plan.yaml"
        plan_content = {"plan": []}
        plan_file.write_text(yaml.dump(plan_content))

        with pytest.raises(ValueError, match="missing 'goal'"):
            _import_plan_from_yaml(str(plan_file))

    def test_import_plan_invalid_action(self, tmp_path):
        """Import fails when action is invalid."""
        plan_file = tmp_path / "plan.yaml"
        plan_content = {
            "goal": "Test",
            "plan": [{"step": 1, "action": "invalid"}],
        }
        plan_file.write_text(yaml.dump(plan_content))

        with pytest.raises(ValueError, match="invalid action"):
            _import_plan_from_yaml(str(plan_file))

    def test_export_plan_to_yaml_string(self):
        """Export plan to YAML string format."""
        plan = SkillPlan(
            goal="Test goal",
            steps=[
                SkillPlanStep(
                    step=1,
                    action="run",
                    skill_name="test-skill",
                    params={"input": "test"},
                    inject="Inject instructions",
                ),
                SkillPlanStep(
                    step=2,
                    action="task",
                    description="Do a task",
                    instructions="Task instructions",
                ),
            ],
            success_criteria="Criteria",
            preparation_plan="Prep plan",
        )

        yaml_str = _plan_to_yaml(plan)

        # Verify it's valid YAML
        data = yaml.safe_load(yaml_str)
        assert data["goal"] == "Test goal"
        assert len(data["plan"]) == 2
        assert data["plan"][0]["skill"] == "test-skill"
        assert data["plan"][0]["inject"] == "Inject instructions"
        assert data["plan"][1]["description"] == "Do a task"

    def test_export_plan_to_file(self, tmp_path):
        """Export plan to file."""
        plan = SkillPlan(
            goal="Test",
            steps=[
                SkillPlanStep(step=1, action="task", description="Test task")
            ],
        )

        output_file = tmp_path / "output.yaml"
        _export_plan_to_file(plan, str(output_file))

        assert output_file.exists()
        data = yaml.safe_load(output_file.read_text())
        assert data["goal"] == "Test"

    def test_export_plan_to_stdout(self, capsys):
        """Export plan to stdout when filepath is '-'."""
        plan = SkillPlan(
            goal="Test stdout",
            steps=[],
        )

        _export_plan_to_file(plan, "-")

        captured = capsys.readouterr()
        assert "Test stdout" in captured.out


class TestExecutionLogExport:
    """Test execution log export functionality."""

    def test_export_execution_log(self, tmp_path):
        """Export execution log to YAML."""
        state = RouterState(
            goal="Test goal",
            attempts=[
                SkillAttempt(
                    action="run",
                    skill_name="test-skill",
                    params={"input": "test"},
                    exit_code=0,
                    runner_summary="Success",
                    context="",
                    context_hint="",
                    success=True,
                    iteration=1,
                    subdir=Path(""),
                    raw_output="Some output",
                ),
            ],
            iteration=1,
            max_iterations=5,
            done=True,
            final_result="Completed",
            success_criteria="Criteria",
            preparation="Preparation plan",
        )

        output_file = tmp_path / "execution.yaml"
        _export_execution_log(state, str(output_file))

        assert output_file.exists()
        data = yaml.safe_load(output_file.read_text())

        assert data["goal"] == "Test goal"
        assert data["status"] == "completed"
        assert len(data["execution"]) == 1
        assert data["execution"][0]["skill"] == "test-skill"
        assert data["execution"][0]["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
