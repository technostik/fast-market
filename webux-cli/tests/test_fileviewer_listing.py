from pathlib import Path

from webux.fileviewer.plugin import _tree


def test_fileviewer_tree_includes_markdown_and_shell_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "README.md").write_text("hello", encoding="utf-8")
    (root / "run.sh").write_text("echo hi", encoding="utf-8")

    tree = _tree(root)
    names = {child["name"] for child in tree.get("children", [])}
    assert "README.md" in names
    assert "run.sh" in names


def test_fileviewer_tree_keeps_other_extensions_visible(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "notes.customext").write_text("x", encoding="utf-8")

    tree = _tree(root)
    names = {child["name"] for child in tree.get("children", [])}
    assert "notes.customext" in names


def test_roots_use_config_data_and_workdir_root(monkeypatch, tmp_path):
    import webux.fileviewer.plugin as plugin

    monkeypatch.setattr(plugin, "get_common_config_path", lambda: Path("/home/user/.config/fast-market/common/config.yaml"))
    monkeypatch.setattr(plugin, "get_data_dir", lambda: Path("/home/user/.local/share/fast-market/data"))
    monkeypatch.setattr(plugin, "load_common_config", lambda: {"workdir": str(tmp_path)})

    roots = plugin._roots()
    assert roots["config"] == Path("/home/user/.config/fast-market")
    assert roots["data"] == Path("/home/user/.local/share/fast-market")
    assert roots["workdir_root"] == tmp_path.resolve()
