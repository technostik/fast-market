"""Unit tests for export/import YAML functionality - no LLM required."""
import pytest
import yaml
from pathlib import Path
import tempfile

from core.plan_utils import (
    parse_global_params,
    build_params_dict,
    validate_mandatory_params,
    PlanParamDef,
    SkillPlan,
    SkillPlanStep,
)
from core.router import (
    _import_plan_from_yaml,
    _plan_to_yaml,
    _execution_log_to_yaml,
    _export_plan_to_file,
    _export_execution_log,
    _substitute_placeholders,
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


class TestGlobalParams:
    """Test global params section parsing and validation."""

    def test_parse_global_params_mandatory(self):
        """Test parsing mandatory params (no default)."""
        param_defs = parse_global_params(["URL", "LANGUAGE"])
        assert len(param_defs) == 2
        assert param_defs[0].name == "URL"
        assert param_defs[0].is_mandatory is True
        assert param_defs[0].default is None
        assert param_defs[1].name == "LANGUAGE"
        assert param_defs[1].is_mandatory is True

    def test_parse_global_params_with_defaults(self):
        """Test parsing params with default values."""
        param_defs = parse_global_params(["URL", "LANGUAGE:fr", "MAX_RESULTS:50"])
        assert len(param_defs) == 3
        assert param_defs[0].name == "URL"
        assert param_defs[0].is_mandatory is True
        assert param_defs[1].name == "LANGUAGE"
        assert param_defs[1].default == "fr"
        assert param_defs[1].is_mandatory is False
        assert param_defs[2].name == "MAX_RESULTS"
        assert param_defs[2].default == "50"
        assert param_defs[2].is_mandatory is False

    def test_build_params_dict_cli_overrides(self):
        """Test that CLI params override global defaults."""
        param_defs = parse_global_params(["URL", "LANGUAGE:fr", "MAX:10"])
        cli_params = {"LANGUAGE": "en", "URL": "https://example.com"}

        result = build_params_dict(param_defs, cli_params)
        assert result["URL"] == "https://example.com"
        assert result["LANGUAGE"] == "en"  # CLI overrides default
        assert result["MAX"] == "10"  # Uses default since not in CLI

    def test_build_params_dict_no_cli(self):
        """Test building params dict without CLI params uses defaults."""
        param_defs = parse_global_params(["URL", "LANGUAGE:fr"])
        # Only params with defaults should be in result
        result = build_params_dict(param_defs, {})
        assert "URL" not in result  # Mandatory, not provided
        assert result["LANGUAGE"] == "fr"

    def test_validate_mandatory_params_missing(self):
        """Test validation fails for missing mandatory params."""
        param_defs = parse_global_params(["URL", "LANGUAGE:fr"])
        provided = {"LANGUAGE": "en"}  # URL is missing

        missing = validate_mandatory_params(param_defs, provided)
        assert "URL" in missing

    def test_validate_mandatory_params_all_provided(self):
        """Test validation passes when all mandatory params provided."""
        param_defs = parse_global_params(["URL", "LANGUAGE:fr"])
        provided = {"URL": "https://example.com", "LANGUAGE": "en"}

        missing = validate_mandatory_params(param_defs, provided)
        assert len(missing) == 0

    def test_import_plan_with_global_params(self, tmp_path):
        """Import a plan with global params section."""
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
"""
        plan_file.write_text(plan_content)

        # Without providing URL, should fail
        with pytest.raises(ValueError, match="Missing required plan parameters"):
            _import_plan_from_yaml(str(plan_file))

        # With URL provided, should succeed
        plan = _import_plan_from_yaml(str(plan_file), params={"URL": "https://example.com"})
        assert plan.goal == "Process https://example.com"
        assert len(plan.steps) == 1
        assert plan.steps[0].skill_name == "test-skill"
        # Params are now empty on the step (global params injected at runtime)
        assert plan.steps[0].params == {}

    def test_import_plan_with_invalid_params_section(self, tmp_path):
        """Import fails with invalid params section format."""
        plan_file = tmp_path / "plan.yaml"
        plan_content = """
goal: Test
params: not_a_list
plan:
  - step: 1
    action: run
    skill: test-skill
"""
        plan_file.write_text(plan_content)

        with pytest.raises(ValueError, match="Invalid 'params' section"):
            _import_plan_from_yaml(str(plan_file))

    def test_import_plan_with_colon_in_default(self, tmp_path):
        """Test that defaults can contain colons (e.g., URLs)."""
        param_defs = parse_global_params(["URL:https://example.com:8080"])
        assert len(param_defs) == 1
        assert param_defs[0].name == "URL"
        assert param_defs[0].default == "https://example.com:8080"


class TestRunDirPlaceholder:
    """Test RUN_DIR placeholder functionality."""

    def test_substitute_run_dir_placeholder(self):
        """Test that {{RUN_DIR}} is substituted correctly."""
        plan_data = {
            "goal": "Test {{RUN_DIR}}",
            "plan": [
                {
                    "step": 1,
                    "action": "run",
                    "skill": "test-skill",
                }
            ]
        }

        params = {"RUN_DIR": "runs/abc123"}
        result = _substitute_placeholders(plan_data, params)

        assert result["goal"] == "Test runs/abc123"

    def test_run_dir_default_value_when_no_isolation(self):
        """Test that RUN_DIR defaults to '.' when no isolation."""
        params = {"RUN_DIR": "."}
        plan_data = {"goal": "Work in {{RUN_DIR}}"}
        result = _substitute_placeholders(plan_data, params)

        assert result["goal"] == "Work in ."

    def test_import_plan_with_run_dir(self, tmp_path):
        """Import a plan with {{RUN_DIR}} placeholder and verify substitution."""
        plan_file = tmp_path / "plan.yaml"
        plan_content = """
goal: Process in {{RUN_DIR}}
params:
  - RUN_DIR:runs/test123
plan:
  - step: 1
    action: run
    skill: test-skill
"""
        plan_file.write_text(plan_content)

        plan = _import_plan_from_yaml(str(plan_file))

        assert plan.goal == "Process in runs/test123"


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
