from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from cli.main import main
from core.models import Prompt
from storage.store import PromptStore


def test_prompt_store_round_trip():
    store = PromptStore(":memory:")
    store.create_prompt(Prompt(name="hello", content="Hello {name}"))
    prompt = store.get_prompt("hello")
    assert prompt is not None
    assert prompt.name == "hello"
    assert prompt.content == "Hello {name}"


def test_prompt_cli_create_list_get_delete(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()

    result = runner.invoke(main, ["create", "summary", "--content", "Summarize {content}"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["list", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["name"] == "summary"

    result = runner.invoke(main, ["get", "summary", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["placeholders"] == ["content"]

    result = runner.invoke(main, ["delete", "summary", "--yes"])
    assert result.exit_code == 0, result.output


def test_prompt_cli_setup_add_and_list_provider(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()

    result = runner.invoke(main, ["setup", "--add-provider", "anthropic"], input="\n\n")
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["setup", "--list-providers"])
    assert result.exit_code == 0, result.output
    assert "anthropic" in result.output
    assert "ANTHROPIC_API_KEY" in result.output


class _FakeProvider:
    def complete(self, request):
        class _Response:
            content = f"RESULT::{request.prompt}"
            model = request.model or "fake-model"
            usage = {"tokens": 1}
            metadata = {"provider": "fake"}

        return _Response()


def test_prompt_cli_apply_literal_and_stdin(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "prompt.yaml").write_text(
        "default_provider: anthropic\nproviders:\n  anthropic:\n    default_model: fake-model\n    api_key_env: ANTHROPIC_API_KEY\n",
        encoding="utf-8",
    )

    import commands.helpers as helpers_mod

    monkeypatch.setattr(helpers_mod, "build_engine", lambda verbose: {"anthropic": _FakeProvider()})

    result = runner.invoke(main, ["create", "summarize", "--content", "Summarize: {content}"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["apply", "summarize", "content=hello"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "RESULT::Summarize: hello"

    result = runner.invoke(main, ["apply", "summarize", "content=-"], input="streamed text")
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "RESULT::Summarize: streamed text"


def test_prompt_cli_apply_from_file_json(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "prompt.yaml").write_text(
        "default_provider: anthropic\nproviders:\n  anthropic:\n    default_model: fake-model\n    api_key_env: ANTHROPIC_API_KEY\n",
        encoding="utf-8",
    )

    import commands.helpers as helpers_mod

    monkeypatch.setattr(helpers_mod, "build_engine", lambda verbose: {"anthropic": _FakeProvider()})

    source = tmp_path / "article.txt"
    source.write_text("file content", encoding="utf-8")

    result = runner.invoke(main, ["create", "summarize_file", "--content", "Summarize: {content}"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["apply", "summarize_file", "--format", "json", f"content=@{source}"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["output"] == "RESULT::Summarize: file content"
    assert payload["model"] == "fake-model"
