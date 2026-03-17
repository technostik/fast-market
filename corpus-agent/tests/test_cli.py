from __future__ import annotations

import importlib
import json


def _main_with_reload():
    import cli.main as cli_mod

    importlib.reload(cli_mod)
    return cli_mod.main


def test_sync_obsidian(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["sync", "--source", "obsidian", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["source"] == "obsidian"
    assert data[0]["indexed"] >= 1


def test_sync_youtube(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["sync", "--source", "youtube", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["source"] == "youtube"
    assert data[0]["indexed"] >= 1


def test_sync_all(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["sync", "--source", "all", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert {r["source"] for r in data} >= {"obsidian", "youtube"}


def test_sync_clean(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["sync", "--source", "obsidian", "--clean", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["indexed"] >= 1


def test_search_keyword(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["search", "hello", "--mode", "keyword", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data) >= 1


def test_search_semantic(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["search", "hello world", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert isinstance(json.loads(result.output), list)


def test_search_text_output(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["search", "hello", "--mode", "keyword"])
    assert result.exit_code == 0, result.output
    assert "score=" in result.output


def test_search_no_results(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["search", "xyzzy_nonexistent_zzz", "--mode", "keyword"])
    assert result.exit_code == 0
    assert "no results" in result.output


def test_get_meta(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["sync", "--source", "obsidian"])
    search = runner.invoke(main, ["search", "hello", "--mode", "keyword", "--format", "json"])
    handle = json.loads(search.output)[0]["handle"]
    result = runner.invoke(main, ["get", handle, "--what", "meta", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["handle"] == handle
    assert "raw_text" not in data


def test_get_content(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["sync", "--source", "obsidian"])
    search = runner.invoke(main, ["search", "hello", "--mode", "keyword", "--format", "json"])
    handle = json.loads(search.output)[0]["handle"]
    result = runner.invoke(main, ["get", handle, "--what", "content"])
    assert result.exit_code == 0
    assert "hello" in result.output.lower()


def test_get_not_found(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["get", "ob-nonexistent-0000"])
    assert result.exit_code == 1


def test_delete_by_handle(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["sync", "--source", "obsidian"])
    search = runner.invoke(main, ["search", "hello", "--mode", "keyword", "--format", "json"])
    handle = json.loads(search.output)[0]["handle"]
    result = runner.invoke(main, ["delete", handle, "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["deleted"] is True
    assert runner.invoke(main, ["get", handle]).exit_code == 1


def test_delete_not_found(runner, mock_env):
    main = _main_with_reload()
    assert runner.invoke(main, ["delete", "ob-nonexistent-0000"]).exit_code == 1


def test_status_after_sync(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["status", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert any(r["source_plugin"] == "obsidian" for r in data)


def test_status_empty(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["status", "--format", "json"])
    assert result.exit_code == 0
    assert isinstance(json.loads(result.output), list)


def test_reindex(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["sync", "--source", "obsidian"])
    result = runner.invoke(main, ["reindex", "--source", "obsidian", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["source"] == "obsidian"
    assert data[0]["documents"] >= 1
    assert data[0]["chunks"] >= 1


def test_plugin_options_in_search_help(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["search", "--help"])
    assert result.exit_code == 0
    assert "--privacy-status" in result.output
    assert "--min-duration" in result.output
    assert "--max-duration" in result.output
    assert "--type" in result.output
    assert "--since" in result.output
    assert "--until" in result.output
    assert "--min-size" in result.output


def test_plugin_options_not_in_status_help(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["status", "--help"])
    assert result.exit_code == 0
    assert "--privacy-status" not in result.output
    assert "--min-duration" not in result.output


def test_source_choices_are_dynamic(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["sync", "--help"])
    assert "obsidian" in result.output
    assert "youtube" in result.output


def test_plugin_removal_simulation(runner, mock_env, monkeypatch):
    from core import registry as reg

    original = reg.discover_plugins

    def obsidian_only(config):
        all_plugins = original(config)
        return {k: v for k, v in all_plugins.items() if k == "obsidian"}

    monkeypatch.setattr(reg, "discover_plugins", obsidian_only)

    import cli.main as cli_mod

    importlib.reload(cli_mod)
    reloaded_main = cli_mod.main

    result = runner.invoke(reloaded_main, ["search", "--help"])
    assert result.exit_code == 0
    assert "--privacy-status" not in result.output

    result = runner.invoke(reloaded_main, ["sync", "--source", "youtube"])
    assert result.exit_code != 0
