from __future__ import annotations

import json
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient

import webux.watcher.register as watcher_mod


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(watcher_mod.router)
    return app


def _client(monkeypatch, stdout="", stderr="", returncode=0, fail=None):
    def fake_run(cmd, **kwargs):
        if fail == "missing":
            raise FileNotFoundError("watcher")
        if fail == "timeout":
            raise subprocess.TimeoutExpired(cmd, 1)
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    monkeypatch.setattr(watcher_mod.subprocess, "run", fake_run)
    return TestClient(_app())


def test_manifest_fields():
    manifest = watcher_mod.register({})
    assert manifest.name == "watcher"
    assert manifest.tab_label == "Watcher"
    assert manifest.lazy is True
    assert "/watcher" in watcher_mod._HTML


def test_frontend_card_split_layout():
    html = watcher_mod._HTML
    assert '<main class="webux-page">' in html
    assert 'class="split"' in html and "cards-grid" in html
    assert 'id="detail"' in html and 'id="detailNews"' in html
    assert 'role="button"' in html and 'tabindex="0"' in html
    assert "<table" not in html and "showHistory" not in html
    assert "/api/watcher/history" in html and "/api/watcher/news" in html
    assert "secondary_value" in html and "toFixed(2)" in html
    assert "card-icon" in html and "newsPager" in html
    assert "showGlobalNews" in html and "detailChart" in html
    assert "pgFirst" in html and "pgNext" in html
    assert "detailGlobal" in html


def test_frontend_tradingview_widget_ranges_and_ratio():
    html = watcher_mod._HTML
    assert 'id="tvChart"' in html and "embed-widget-advanced-chart.js" in html
    assert 'id="rangeRow"' in html
    for label in (">1D<", ">1W<", ">1M<", ">1Y<", ">10Y<", ">MAX<"):
        assert label in html
    assert 'id="ratioBox"' in html and "premium" in html and "5.806" in html
    assert "loadTradingView" in html and "tvSymbolFor" in html
    assert "DEFAULT_TV" in html and "TVC:FR10Y" in html and "OANDA:XAUUSD" in html
    # Bond yields (TVC) + NASDAQ:IXIC are blocked in free TV embeds → native chart
    assert "NATIVE_CHART" in html and 'id="nativeChart"' in html
    assert "loadNativeChart" in html and "loadChart" in html
    assert "MONTHLY" in html and "clearNative" in html
    assert "selectedId !== id" in html  # stale responses never paint another variable
    for rid in ("fr_10y", "us_10y", "uk_10y", "de_10y", "nasdaq"):
        assert rid in html
    for rng in ('data-range="1D"', 'data-range="1W"', 'data-range="1M"', 'data-range="1Y"', 'data-range="10Y"', 'data-range="MAX"'):
        assert rng in html
    assert 'id="spark"' not in html  # canvas sparkline replaced by lightweight widget


def test_dashboard_refresh_forwarded_to_cli(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"variables": [], "news": []}), "")

    monkeypatch.setattr(watcher_mod.subprocess, "run", fake_run)
    assert TestClient(_app()).get("/dashboard", params={"refresh": "true"}).status_code == 200
    assert "--refresh" in seen["cmd"]
    assert TestClient(_app()).get("/dashboard").status_code == 200
    assert "--refresh" not in seen["cmd"]


def test_dashboard_currency_forwarded_to_cli(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"variables": [], "news": []}), "")

    monkeypatch.setattr(watcher_mod.subprocess, "run", fake_run)
    assert TestClient(_app()).get("/dashboard", params={"main_currency": "EUR"}).status_code == 200
    assert "--main-currency" in seen["cmd"] and "EUR" in seen["cmd"]
    assert TestClient(_app()).get("/dashboard").status_code == 200
    assert seen["cmd"].count("--main-currency") == 1 and "USD" in seen["cmd"]


def test_dashboard_passthrough(monkeypatch):
    payload = {"generated_at": "x", "variables": [{"id": "fr_10y"}], "news": []}
    c = _client(monkeypatch, stdout=json.dumps(payload))
    r = c.get("/dashboard", params={"last": 5})
    assert r.status_code == 200
    assert r.json()["variables"] == [{"id": "fr_10y"}]
    assert r.json()["exit_code"] == 0


def test_dashboard_partial_errors_still_returns_data(monkeypatch):
    payload = {"variables": [{"id": "fr_10y", "error": "boom"}], "news": []}
    c = _client(monkeypatch, stdout=json.dumps(payload), returncode=1)
    r = c.get("/dashboard")
    assert r.status_code == 200
    assert r.json()["exit_code"] == 1


def test_dashboard_total_failure_is_502(monkeypatch):
    c = _client(monkeypatch, stdout="", stderr="config exploded", returncode=1)
    r = c.get("/dashboard")
    assert r.status_code == 502


def test_dashboard_missing_cli_is_503(monkeypatch):
    c = _client(monkeypatch, fail="missing")
    assert c.get("/dashboard").status_code == 503


def test_history_unknown_variable_is_404(monkeypatch):
    c = _client(monkeypatch, stdout="", stderr="Error: Unknown variable 'nope'", returncode=1)
    assert c.get("/history", params={"variable": "nope"}).status_code == 404


def test_profile_forwarded_to_cli(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"variables": [], "news": []}), "")

    monkeypatch.setattr(watcher_mod.subprocess, "run", fake_run)
    r = TestClient(_app()).get("/dashboard", params={"profile": "joriel"})
    assert r.status_code == 200
    assert seen["cmd"][:3] == ["watcher", "-P", "joriel"]


def test_news_variable_passthrough(monkeypatch):
    payload = {"generated_at": "x", "news": [{"topic": "bitcoin_regulation", "title": "t"}]}
    c = _client(monkeypatch, stdout=json.dumps(payload))
    r = c.get("/news", params={"variable": "bitcoin"})
    assert r.status_code == 200
    assert r.json()["news"][0]["topic"] == "bitcoin_regulation"


def test_news_unknown_variable_is_404(monkeypatch):
    c = _client(monkeypatch, stdout="", stderr="Error: Unknown variable 'nope'", returncode=1)
    assert c.get("/news", params={"variable": "nope"}).status_code == 404
