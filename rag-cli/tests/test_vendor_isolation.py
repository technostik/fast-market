from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

RAG_CLI_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = RAG_CLI_ROOT / "_vendor"


def _find_imports_in_file(filepath: Path) -> list[str]:
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _collect_python_files(root: Path, exclude_dirs: list[str]) -> list[Path]:
    files = []
    for item in root.rglob("*.py"):
        rel = item.relative_to(root)
        if any(part in exclude_dirs for part in rel.parts):
            continue
        files.append(item)
    return files


def test_no_rag_cli_code_imports_from_vendor():
    exclude_dirs = ["_vendor", "tests"]
    py_files = _collect_python_files(RAG_CLI_ROOT, exclude_dirs)
    violations = []

    for filepath in py_files:
        imports = _find_imports_in_file(filepath)
        for imp in imports:
            if imp.startswith("_vendor") or "pageindex" in imp.lower():
                violations.append(f"{filepath.relative_to(RAG_CLI_ROOT)}: imports {imp!r}")

    assert not violations, (
        "Found imports from _vendor/ in rag-cli code:\n"
        + "\n".join(violations)
    )
