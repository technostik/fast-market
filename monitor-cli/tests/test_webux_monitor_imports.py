from __future__ import annotations

import types

from webux.monitor.register import _get_monitor_storage_class


def test_monitor_storage_import_isolated_from_other_core_modules(monkeypatch):
    fake_core = types.ModuleType("core")
    fake_models = types.ModuleType("core.models")

    monkeypatch.setitem(__import__("sys").modules, "core", fake_core)
    monkeypatch.setitem(__import__("sys").modules, "core.models", fake_models)

    storage_cls = _get_monitor_storage_class()
    assert storage_cls.__name__ == "MonitorStorage"

    # original fake modules are restored after isolated import helper exits
    assert __import__("sys").modules["core"] is fake_core
    assert __import__("sys").modules["core.models"] is fake_models
