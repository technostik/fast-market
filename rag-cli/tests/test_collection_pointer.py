from __future__ import annotations

import os
import pytest
from core.collection_pointer import (
    read_active_collection,
    write_active_collection,
    resolve_collection_name,
)


def test_write_and_read_active_collection(tmp_path, monkeypatch):
    pointer_dir = tmp_path / "rag"
    pointer_dir.mkdir()
    monkeypatch.setattr(
        "core.collection_pointer._pointer_path",
        lambda profile=None: pointer_dir / "active_collection",
    )
    write_active_collection("my-collection")
    assert read_active_collection() == "my-collection"


def test_read_active_collection_none_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.collection_pointer._pointer_path",
        lambda profile=None: tmp_path / "nonexistent",
    )
    assert read_active_collection() is None


def test_resolve_collection_name_cli_override():
    result = resolve_collection_name(cli_override="override-name")
    assert result == "override-name"


def test_resolve_collection_name_active(tmp_path, monkeypatch):
    pointer_dir = tmp_path / "rag"
    pointer_dir.mkdir()
    monkeypatch.setattr(
        "core.collection_pointer._pointer_path",
        lambda profile=None: pointer_dir / "active_collection",
    )
    write_active_collection("active-one")
    assert resolve_collection_name() == "active-one"


def test_resolve_collection_name_raises_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.collection_pointer._pointer_path",
        lambda profile=None: tmp_path / "nonexistent",
    )
    with pytest.raises(SystemExit):
        resolve_collection_name()


def test_write_active_collection_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        write_active_collection("")
