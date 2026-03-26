def test_discover_finds_test_skills(skills_dir):
    from common.skill.skill import discover_skills

    skills = discover_skills(skills_dir)
    names = [s.name for s in skills]
    assert "test-echo" in names
    assert "test-fail" in names
    assert "test-prompt" in names


def test_skill_loads_name_and_description(test_echo_skill):
    assert test_echo_skill.name == "test-echo"
    assert "echo" in test_echo_skill.description.lower()


def test_skill_loads_parameters(test_echo_skill):
    assert len(test_echo_skill.parameters) == 2
    required = [p for p in test_echo_skill.parameters if p.get("required")]
    assert len(required) == 1
    assert required[0]["name"] == "message"


def test_skill_has_scripts(test_echo_skill):
    assert test_echo_skill.has_scripts is True


def test_skill_get_body_returns_content(skills_dir):
    from common.skill.skill import Skill

    skill = Skill.from_path(skills_dir / "test-prompt")
    body = skill.get_body()
    assert "PROMPT_SKILL_OK" in body


def test_skill_without_parameters_has_empty_list(skills_dir):
    from common.skill.skill import Skill

    skill = Skill.from_path(skills_dir / "test-prompt")
    assert skill.parameters == []


def test_nonexistent_skill_returns_none(skills_dir):
    from common.skill.skill import Skill

    result = Skill.from_path(skills_dir / "does-not-exist")
    assert result is None
