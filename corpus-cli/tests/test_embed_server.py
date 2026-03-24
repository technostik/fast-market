from __future__ import annotations

from click.testing import CliRunner


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Process:
    def __init__(self, pid: int):
        self.pid = pid


def _main_with_reload():
    import importlib
    import cli.main as cli_mod

    importlib.reload(cli_mod)
    return cli_mod.main


def test_embed_server_start_status_stop(runner, mock_env, monkeypatch):
    import commands.embed_server.register as mod

    state = {"running": False, "pid": 44556}

    def fake_popen(*args, **kwargs):
        state["running"] = True
        return _Process(state["pid"])

    def fake_kill(pid, sig):
        if sig == 0 and not state["running"]:
            raise ProcessLookupError
        if sig in (15, 9):
            state["running"] = False

    def fake_health(port, timeout=1.5):
        if state["running"]:
            return {"status": "ok", "model": "paraphrase-multilingual-mpnet-base-v2", "model_loaded": True}
        return None

    monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mod.os, "kill", fake_kill)
    monkeypatch.setattr(mod, "_health", fake_health)

    main = _main_with_reload()
    local_runner = CliRunner()

    result = local_runner.invoke(main, ["embed-server", "start", "--port", "28765"])
    assert result.exit_code == 0, result.output
    assert "started in background" in result.output.lower()

    result = local_runner.invoke(main, ["embed-server", "status"])
    assert result.exit_code == 0
    assert "RUNNING" in result.output
    assert "Health: OK" in result.output

    result = local_runner.invoke(main, ["embed-server", "stop"])
    assert result.exit_code == 0, result.output


def test_embedder_server_detection(monkeypatch):
    from core.embedder import Embedder

    class httpx_ok:
        @staticmethod
        def get(url, timeout=1.0):
            return _Resp(200, {"model": "m", "model_loaded": True})

    monkeypatch.setitem(__import__("sys").modules, "httpx", httpx_ok)
    embedder = Embedder(model_name="m", server_url="http://127.0.0.1:1234")
    assert embedder._use_server is True


def test_embedder_falls_back_when_server_fails(monkeypatch):
    from core.embedder import Embedder

    class httpx_mix:
        @staticmethod
        def get(url, timeout=1.0):
            return _Resp(200, {"model": "m", "model_loaded": True})

        @staticmethod
        def post(url, json=None, timeout=30.0):
            raise RuntimeError("boom")

    monkeypatch.setitem(__import__("sys").modules, "httpx", httpx_mix)

    embedder = Embedder(model_name="m", server_url="http://127.0.0.1:1234")

    monkeypatch.setattr(
        Embedder,
        "_embed_via_local_model",
        lambda self, texts: [(self.hash_text(text), [1.0, 0.0]) for text in texts],
    )

    out = embedder.embed_texts(["hello"])
    assert len(out) == 1
    assert embedder._use_server is False
