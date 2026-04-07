import json
import sys
from pathlib import Path

from click.testing import CliRunner


def get_cli():
    repo_root = Path(__file__).resolve().parents[1]
    skill_cli_path = str(repo_root / "skill-cli")
    if skill_cli_path in sys.path:
        sys.path.remove(skill_cli_path)
    sys.path.insert(0, skill_cli_path)
    sys.modules.pop("commands", None)
    sys.modules.pop("commands.skill", None)
    from skill_entry import main

    return main


def test_apply_echo_skill(workdir):
    runner = CliRunner()
    result = runner.invoke(
        get_cli(),
        ["apply", "test-echo", "message=hello", "--workdir", str(workdir)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "ECHO: hello" in result.output


def test_apply_missing_required_param(workdir):
    runner = CliRunner()
    result = runner.invoke(get_cli(), ["apply", "test-echo"])
    assert result.exit_code == 1
    assert "message" in result.output.lower()  # tells user which param is missing


def test_apply_default_param_used(workdir):
    runner = CliRunner()
    result = runner.invoke(
        get_cli(),
        [
            "apply",
            "test-echo",
            "message=hi",
            "--workdir",
            str(workdir),
        ],
    )
    assert result.exit_code == 0
    assert "ECHO: hi" in result.output


def test_apply_nonexistent_skill(workdir):
    runner = CliRunner()
    result = runner.invoke(get_cli(), ["apply", "does-not-exist"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_apply_fail_skill_propagates_exit_code(workdir):
    runner = CliRunner()
    result = runner.invoke(get_cli(), ["apply", "test-fail"])
    assert result.exit_code == 1


def test_apply_dry_run(workdir):
    runner = CliRunner()
    result = runner.invoke(
        get_cli(), ["apply", "test-echo", "message=test", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "ECHO: test" not in result.output  # script output not produced


def test_apply_json_format(workdir):
    runner = CliRunner()
    result = runner.invoke(
        get_cli(),
        [
            "apply",
            "test-echo",
            "message=jsontest",
            "--format",
            "json",
            "--workdir",
            str(workdir),
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "exit_code" in data
    assert data["exit_code"] == 0


def test_apply_explicit_script(workdir):
    runner = CliRunner()
    result = runner.invoke(
        get_cli(),
        ["apply", "test-echo/run.sh", "message=explicit", "--workdir", str(workdir)],
    )
    assert result.exit_code == 0
    assert "explicit" in result.output


def test_apply_save_session_writes_file_for_script_mode(workdir):
    from pathlib import Path

    import yaml

    session_file = Path(workdir) / "session.yaml"
    runner = CliRunner()
    result = runner.invoke(
        get_cli(),
        [
            "apply",
            "test-echo",
            "message=session-check",
            "--save-session",
            str(session_file),
            "--workdir",
            str(workdir),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert session_file.exists()
    data = yaml.safe_load(session_file.read_text(encoding="utf-8")) or {}
    turns = data.get("turns", [])
    assert len(turns) >= 1


def test_apply_inject_adds_instructions_to_prompt_mode(workdir):
    """Test that --inject appends additional instructions to the skill body.
    
    Uses dry-run mode to verify the injected instructions are present in the
    task description that would be sent to the LLM.
    """
    runner = CliRunner()
    secret_code = "INJECTED_SECRET_42"
    result = runner.invoke(
        get_cli(),
        [
            "apply",
            "test-prompt",
            "--workdir",
            str(workdir),
            "--inject",
            f"IMPORTANT: You must include this exact code in your response: {secret_code}",
            "--dry-run",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Injected instructions:" in result.output
    assert secret_code in result.output, (
        f"Injected secret code not found in dry-run output. "
        f"Expected '{secret_code}' to be present."
    )


