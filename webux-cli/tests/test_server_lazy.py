from __future__ import annotations

from fastapi import APIRouter
from fastapi.testclient import TestClient

from common.webux.base import WebuxPluginManifest
from core.server import build_app


def _route_paths(app):
    return {route.path for route in app.router.routes}


def test_lazy_plugin_mounts_router_on_first_page_request():
    router = APIRouter()

    @router.get("/ping")
    def ping():
        return {"ok": True}

    plugin = WebuxPluginManifest(
        name="lazyplug",
        tab_label="Lazy",
        tab_icon="🧪",
        api_router=router,
        frontend_html="<html><body><main>lazy</main></body></html>",
        lazy=True,
    )
    app = build_app(config={}, plugins={"lazyplug": plugin})

    assert "/api/lazyplug/ping" not in _route_paths(app)

    client = TestClient(app)
    page = client.get("/lazyplug")
    assert page.status_code == 200
    assert "/api/lazyplug/ping" in _route_paths(app)

    api = client.get("/api/lazyplug/ping")
    assert api.status_code == 200
    assert api.json() == {"ok": True}
