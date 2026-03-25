def test_execute_echo_skill(workdir, skills_dir):
    from common.skill.runner import execute_skill_script

    result = execute_skill_script("test-echo", workdir, params={"message": "hello"})
    assert result.exit_code == 0
    assert "ECHO: hello" in result.stdout


def test_execute_echo_with_prefix(workdir, skills_dir):
    from common.skill.runner import execute_skill_script

    result = execute_skill_script(
        "test-echo", workdir, params={"message": "world", "prefix": "TEST"}
    )
    assert result.exit_code == 0
    assert "TEST: world" in result.stdout


def test_execute_fail_skill(workdir, skills_dir):
    from common.skill.runner import execute_skill_script

    result = execute_skill_script("test-fail", workdir)
    assert result.exit_code == 1
    assert result.timed_out is False


def test_execute_nonexistent_skill(workdir):
    from common.skill.runner import execute_skill_script

    result = execute_skill_script("does-not-exist", workdir)
    assert result.exit_code == 127
    assert "not found" in result.stderr.lower()


def test_resolve_skill_script_single_script(skills_dir):
    from common.skill.runner import resolve_skill_script

    skill, script = resolve_skill_script("test-echo")
    assert skill is not None
    assert script is not None
    assert script.name == "run.sh"


def test_resolve_skill_script_explicit(skills_dir):
    from common.skill.runner import resolve_skill_script

    skill, script = resolve_skill_script("test-echo/run.sh")
    assert skill is not None
    assert script is not None
    assert script.name == "run.sh"


def test_resolve_nonexistent_returns_none(skills_dir):
    from common.skill.runner import resolve_skill_script

    skill, script = resolve_skill_script("does-not-exist")
    assert skill is None
    assert script is None


def test_params_passed_as_env_vars(workdir, skills_dir):
    """Verify SKILL_* env vars are set correctly."""
    from common.skill.runner import execute_skill_script

    # test-echo prints SKILL_PREFIX: SKILL_MESSAGE
    result = execute_skill_script(
        "test-echo", workdir, params={"message": "env-test", "prefix": "PREFIX"}
    )
    assert "PREFIX: env-test" in result.stdout


def test_timeout_triggers(workdir, tmp_path, skills_dir):
    """Create a slow skill on the fly and verify timeout works."""
    import shutil

    slow_skill_dir = tmp_path / "test-slow"
    slow_skill_dir.mkdir()
    (slow_skill_dir / "SKILL.md").write_text(
        "---\nname: test-slow\ndescription: slow\n---\n", encoding="utf-8"
    )
    scripts = slow_skill_dir / "scripts"
    scripts.mkdir()
    run_sh = scripts / "run.sh"
    run_sh.write_text("#!/usr/bin/env bash\nsleep 10\n", encoding="utf-8")
    run_sh.chmod(0o755)

    # temporarily add to skills dir — write directly
    target = skills_dir / "test-slow"
    shutil.copytree(slow_skill_dir, target)

    try:
        from common.skill.runner import execute_skill_script

        result = execute_skill_script("test-slow", workdir, timeout=1)
        assert result.timed_out is True
        assert result.exit_code == 124
    finally:
        shutil.rmtree(target)
