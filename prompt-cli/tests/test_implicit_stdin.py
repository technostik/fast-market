from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from cli.main import main


class _FakeProvider:
    def complete(self, request):
        class _Response:
            content = f"RESULT::{request.prompt}"
            model = request.model or "fake-model"
            usage = {"tokens": 1}
            metadata = {"provider": "fake"}

        return _Response()


def test_implicit_stdin_one_placeholder(
    runner: CliRunner, tmp_path: Path, monkeypatch
):
    """Test that implicit stdin replaces the sole placeholder with a warning."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "prompt.yaml").write_text(
        "default_provider: anthropic\nproviders:\n  anthropic:\n    default_model: fake-model\n    api_key_env: ANTHROPIC_API_KEY\n",
        encoding="utf-8",
    )

    import commands.helpers as helpers_mod

    monkeypatch.setattr(
        helpers_mod, "build_engine", lambda verbose: {"anthropic": _FakeProvider()}
    )

    # Create a prompt with ONE placeholder
    result = runner.invoke(
        main, ["create", "extract_keywords", "--content", "Extract keywords from: {text}"]
    )
    assert result.exit_code == 0, result.output

    # Apply with implicit stdin (one placeholder)
    result = runner.invoke(
        main, ["apply", "extract_keywords"], input="Python is a programming language"
    )
    assert result.exit_code == 0, result.output
    assert "Warning: replacing placeholder 'text' with stdin content" in result.output
    assert "RESULT::Extract keywords from: Python is a programming language" in result.output


def test_implicit_stdin_no_placeholders_error(
    runner: CliRunner, tmp_path: Path, monkeypatch
):
    """Test that implicit stdin raises error when prompt has no placeholders."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()

    # Create a prompt with NO placeholders
    result = runner.invoke(
        main, ["create", "greeting", "--content", "Hello, welcome to our service!"]
    )
    assert result.exit_code == 0, result.output

    # Apply with implicit stdin (no placeholders -> error)
    result = runner.invoke(
        main, ["apply", "greeting"], input="some content"
    )
    assert result.exit_code == 1, result.output
    assert "this prompt should not have additional content" in result.output


def test_implicit_stdin_multiple_placeholders_error(
    runner: CliRunner, tmp_path: Path, monkeypatch
):
    """Test that implicit stdin raises error when prompt has multiple placeholders."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()

    # Create a prompt with MULTIPLE placeholders
    result = runner.invoke(
        main, ["create", "translate", "--content", "Translate {text} from {source_lang} to {target_lang}"]
    )
    assert result.exit_code == 0, result.output

    # Apply with implicit stdin (multiple placeholders -> error)
    result = runner.invoke(
        main, ["apply", "translate"], input="Bonjour le monde"
    )
    assert result.exit_code == 1, result.output
    assert "has 3 placeholders: source_lang, target_lang, text" in result.output
    assert "source_lang=value target_lang=value text=value" in result.output


def test_implicit_stdin_with_explicit_args_uses_args(
    runner: CliRunner, tmp_path: Path, monkeypatch
):
    """Test that when explicit args are provided, stdin is ignored."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "prompt.yaml").write_text(
        "default_provider: anthropic\nproviders:\n  anthropic:\n    default_model: fake-model\n    api_key_env: ANTHROPIC_API_KEY\n",
        encoding="utf-8",
    )

    import commands.helpers as helpers_mod

    monkeypatch.setattr(
        helpers_mod, "build_engine", lambda verbose: {"anthropic": _FakeProvider()}
    )

    # Create a prompt with ONE placeholder
    result = runner.invoke(
        main, ["create", "summarize", "--content", "Summarize: {content}"]
    )
    assert result.exit_code == 0, result.output

    # When both stdin and explicit args are provided, explicit args take precedence
    result = runner.invoke(
        main, ["apply", "summarize", "content=explicit_value"], input="stdin content"
    )
    assert result.exit_code == 0, result.output
    assert "RESULT::Summarize: explicit_value" in result.output
    assert "stdin content" not in result.output


def test_implicit_stdin_unknown_prompt_error(
    runner: CliRunner, tmp_path: Path, monkeypatch
):
    """Test that implicit stdin raises error for unknown prompt name."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()

    # Apply with implicit stdin for non-existent prompt
    result = runner.invoke(
        main, ["apply", "nonexistent_prompt"], input="some content"
    )
    assert result.exit_code == 1, result.output
    assert "Unknown prompt 'nonexistent_prompt'" in result.output


def test_explicit_stdin_flag_still_works(
    runner: CliRunner, tmp_path: Path, monkeypatch
):
    """Test that explicit --stdin flag still coexists and works as before."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "prompt.yaml").write_text(
        "default_provider: anthropic\nproviders:\n  anthropic:\n    default_model: fake-model\n    api_key_env: ANTHROPIC_API_KEY\n",
        encoding="utf-8",
    )

    import commands.helpers as helpers_mod

    monkeypatch.setattr(
        helpers_mod, "build_engine", lambda verbose: {"anthropic": _FakeProvider()}
    )

    # Create a prompt with ONE placeholder
    result = runner.invoke(
        main, ["create", "process", "--content", "Process: {data}"]
    )
    assert result.exit_code == 0, result.output

    # --stdin flag should still raise error for named prompts with placeholders
    result = runner.invoke(
        main, ["apply", "process", "--stdin"], input="some data"
    )
    assert result.exit_code == 1, result.output
    assert "--stdin is not compatible with applying a named prompt" in result.output
