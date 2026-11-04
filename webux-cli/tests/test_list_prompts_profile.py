"""`/list-prompts?profile=` must scope the prompt CLI to that profile.

The endpoint copies the environment and sets FASTMARKET_PROFILE for the
subprocess only: mutating os.environ would race with a running pipeline that
already owns the process-wide profile.
"""

from __future__ import annotations

import asyncio
import os

import webux.long_publish.register as long_reg
import webux.short_publish.register as short_reg


class _FakeProc:
    async def communicate(self):
        return b"alpha\nbeta\n", b""


def _patch_exec(monkeypatch, module) -> dict:
    captured: dict = {}

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env") or {}
        return _FakeProc()

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", fake_exec)
    return captured


def test_short_publish_list_prompts_uses_requested_profile(monkeypatch):
    captured = _patch_exec(monkeypatch, short_reg)
    before = os.environ.get("FASTMARKET_PROFILE")

    result = asyncio.run(short_reg.list_prompts(profile="techno_sophia"))

    assert result == {"prompts": ["alpha", "beta"]}
    assert captured["env"]["FASTMARKET_PROFILE"] == "techno_sophia"
    # Process-wide environment must be untouched.
    assert os.environ.get("FASTMARKET_PROFILE") == before


def test_short_publish_list_prompts_without_profile(monkeypatch):
    captured = _patch_exec(monkeypatch, short_reg)
    monkeypatch.delenv("FASTMARKET_PROFILE", raising=False)

    asyncio.run(short_reg.list_prompts(profile=None))

    assert "FASTMARKET_PROFILE" not in captured["env"]


def test_long_publish_list_prompts_uses_requested_profile(monkeypatch):
    captured = _patch_exec(monkeypatch, long_reg)
    before = os.environ.get("FASTMARKET_PROFILE")

    result = asyncio.run(long_reg.list_prompts(profile="joriel"))

    assert result == {"prompts": ["alpha", "beta"]}
    assert captured["env"]["FASTMARKET_PROFILE"] == "joriel"
    assert os.environ.get("FASTMARKET_PROFILE") == before


def test_long_publish_list_prompts_without_profile(monkeypatch):
    captured = _patch_exec(monkeypatch, long_reg)
    monkeypatch.delenv("FASTMARKET_PROFILE", raising=False)

    asyncio.run(long_reg.list_prompts(profile=None))

    assert "FASTMARKET_PROFILE" not in captured["env"]
