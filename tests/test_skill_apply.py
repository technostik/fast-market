import json

from click.testing import CliRunner


def get_cli():
    from skill_entry import main

    return main


def test_apply_echo_skill(workdir):
    runner = CliRunner()
    result = runner.invoke(get_cli(), ["apply", "test-echo", "message=hello"], catch_exceptions=False)
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
            # prefix not provided, default "ECHO" should be used
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
    result = runner.invoke(get_cli(), ["apply", "test-echo", "message=test", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "ECHO: test" not in result.output  # script output not produced


def test_apply_json_format(workdir):
    runner = CliRunner()
    result = runner.invoke(
        get_cli(), ["apply", "test-echo", "message=jsontest", "--format", "json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "exit_code" in data
    assert data["exit_code"] == 0


def test_apply_explicit_script(workdir):
    runner = CliRunner()
    result = runner.invoke(get_cli(), ["apply", "test-echo/run.sh", "message=explicit"])
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
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert session_file.exists()
    data = yaml.safe_load(session_file.read_text(encoding="utf-8")) or {}
    turns = data.get("turns", [])
    assert len(turns) >= 1
