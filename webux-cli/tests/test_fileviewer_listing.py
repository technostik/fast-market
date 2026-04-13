from pathlib import Path

from webux.fileviewer.plugin import _is_listable_file


def test_fileviewer_lists_markdown_and_shell_files():
    assert _is_listable_file(Path("README.md"))
    assert _is_listable_file(Path("script.sh"))
