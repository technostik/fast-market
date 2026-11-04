"""check-resume must return the profile persisted in the meta log.

The frontend uses it for Retry/Resume so a page-picker change can never move a
half-processed video to a different YouTube account.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import webux.long_publish.register as long_reg
import webux.short_publish.register as short_reg


def _client(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_short_check_resume_returns_meta_profile(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    (tmp_path / "clip-meta.json").write_text(
        json.dumps(
            {
                "source": str(src),
                "profile": "techno_sophia",
                "completed_steps": [0],
                "skipped_steps": [],
                "files": {},
            }
        ),
        encoding="utf-8",
    )

    with _client(short_reg.router) as client:
        body = client.post("/check-resume", json={"source": str(src)}).json()

    assert body["profile"] == "techno_sophia"


def test_short_check_resume_profile_is_empty_without_meta(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")

    with _client(short_reg.router) as client:
        body = client.post("/check-resume", json={"source": str(src)}).json()

    assert body["profile"] == ""


def test_long_check_resume_returns_meta_profile(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    (tmp_path / "clip-long-meta.json").write_text(
        json.dumps(
            {
                "source": str(src),
                "profile": "joriel",
                "completed_steps": [0, 1, 2],
                "skipped_steps": [],
                "files": {},
            }
        ),
        encoding="utf-8",
    )

    with _client(long_reg.router) as client:
        body = client.post("/check-resume", json={"source": str(src)}).json()

    assert body["profile"] == "joriel"


def test_long_check_resume_profile_is_empty_without_meta(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")

    with _client(long_reg.router) as client:
        body = client.post("/check-resume", json={"source": str(src)}).json()

    assert body["profile"] == ""
