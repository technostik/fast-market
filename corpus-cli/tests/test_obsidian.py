from __future__ import annotations

from plugins.obsidian.plugin import ObsidianPlugin


def test_obsidian_fetch_parses_tags_and_links(tmp_path):
    note = tmp_path / "Note.md"
    note.write_text("---\ntags:\n  - alpha\n---\n# T\nhello [[World]] #beta", encoding="utf-8")
    plugin = ObsidianPlugin({"obsidian": {"vault_path": str(tmp_path)}})
    item = plugin.list_items(limit=1)[0]
    doc = plugin.fetch(item)
    assert "alpha" in doc.tags
    assert "beta" in doc.tags
    assert doc.links == ["World"]
    assert "World" in doc.raw_text
