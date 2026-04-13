from __future__ import annotations

from dataclasses import dataclass

import pytest

from common.webux.base import WebuxPluginManifest
from common.webux.registry import discover_webux_plugins


@dataclass
class _EP:
    name: str
    value: str
    loader: object

    def load(self):
        if isinstance(self.loader, Exception):
            raise self.loader
        return self.loader


def test_discover_webux_plugins_success(monkeypatch):
    def register(config):
        return WebuxPluginManifest(
            name="alpha",
            tab_label="Alpha",
            tab_icon="A",
            frontend_html="<html><body>a</body></html>",
        )

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: [_EP(name="alpha", value="x:y", loader=register)],
    )
    plugins = discover_webux_plugins({})
    assert list(plugins.keys()) == ["alpha"]


def test_discover_webux_plugins_register_raises(monkeypatch):
    def register(config):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: [_EP(name="broken", value="x:y", loader=register)],
    )
    with pytest.raises(RuntimeError, match="FAIL LOUDLY"):
        discover_webux_plugins({})


def test_discover_webux_plugins_wrong_type(monkeypatch):
    def register(config):
        return {"name": "bad"}

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: [_EP(name="bad", value="x:y", loader=register)],
    )
    with pytest.raises(TypeError, match="WebuxPluginManifest"):
        discover_webux_plugins({})


def test_discover_webux_plugins_duplicate_name(monkeypatch):
    def r1(config):
        return WebuxPluginManifest(
            name="dup",
            tab_label="One",
            tab_icon="1",
            frontend_html="<html><body>1</body></html>",
            order=1,
        )

    def r2(config):
        return WebuxPluginManifest(
            name="dup",
            tab_label="Two",
            tab_icon="2",
            frontend_html="<html><body>2</body></html>",
            order=2,
        )

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: [
            _EP(name="dup1", value="x:y", loader=r1),
            _EP(name="dup2", value="x:z", loader=r2),
        ],
    )
    with pytest.raises(RuntimeError, match="duplicate webux plugin name"):
        discover_webux_plugins({})
