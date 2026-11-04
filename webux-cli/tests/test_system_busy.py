"""`GET /api/system/busy` aggregates plugin busy probes for the toolbar lock."""

from __future__ import annotations

from fastapi.testclient import TestClient

from common.webux.base import WebuxPluginManifest
from core.server import build_app


def _plugin(name: str, check) -> WebuxPluginManifest:
    return WebuxPluginManifest(
        name=name,
        tab_label=name,
        tab_icon="•",
        api_router=None,
        frontend_html="<html><body><main></main></body></html>",
        lazy=True,
        busy_check=check,
    )


def _client(plugins: dict[str, WebuxPluginManifest]) -> TestClient:
    return TestClient(build_app(config={}, plugins=plugins))


def test_busy_reports_only_active_plugins():
    client = _client(
        {
            "idle": _plugin("idle", lambda: False),
            "busy": _plugin("busy", lambda: True),
        }
    )
    with client:
        assert client.get("/api/system/busy").json() == {
            "busy": True,
            "active": ["busy"],
        }


def test_busy_is_false_when_everything_is_idle():
    client = _client({"idle": _plugin("idle", lambda: False)})
    with client:
        assert client.get("/api/system/busy").json() == {
            "busy": False,
            "active": [],
        }


def test_busy_ignores_plugin_without_probe():
    client = _client({"plain": _plugin("plain", None)})
    with client:
        assert client.get("/api/system/busy").json() == {
            "busy": False,
            "active": [],
        }


def test_busy_ignores_failing_probe():
    def boom() -> bool:
        raise RuntimeError("probe exploded")

    client = _client({"broken": _plugin("broken", boom)})
    with client:
        assert client.get("/api/system/busy").json() == {
            "busy": False,
            "active": [],
        }
