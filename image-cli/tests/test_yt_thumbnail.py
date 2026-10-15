from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webux.yt_thumbnail import register as yt_thumb  # noqa: E402


@pytest.fixture
def video_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fake video source dir with one video, pointed at via youtube config."""
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake-video")
    monkeypatch.setattr(
        yt_thumb, "_source_dir", lambda: tmp_path.resolve()
    )
    monkeypatch.setattr(
        yt_thumb, "_publish_cfg",
        lambda: {"video_source_path": str(tmp_path), "video_extensions": "mp4,mkv,webm"},
    )
    return tmp_path


class TestManifest:
    def test_tab_registration(self):
        manifest = yt_thumb.register({})
        assert manifest.name == "yt_thumbnail"
        assert manifest.tab_label == "YT Thumbnail"
        assert manifest.group == "Publish"
        assert manifest.order == 47
        assert manifest.lazy is True
        paths = {r.path for r in manifest.api_router.routes}
        assert {
            "/compose", "/edit", "/overlay", "/list-videos", "/history",
            "/upload-sources", "/push-thumbnail", "/download", "/config",
            "/list-engines", "/job/{job_id}",
        } <= paths


class TestHelpers:
    def test_next_version_empty(self, tmp_path: Path):
        assert yt_thumb._next_version(tmp_path, "video") == 1

    def test_next_version_increments(self, tmp_path: Path):
        # Only base files (``<stem>_thumb_<N>``) drive the counter —
        # overlay sidecars (``<stem>_thumb_overlay_<N>``) do not, same as
        # long_publish.
        (tmp_path / "video_thumb_1.png").touch()
        (tmp_path / "video_thumb_overlay_2.png").touch()
        assert yt_thumb._next_version(tmp_path, "video") == 2

    def test_place_thumb_renames(self, tmp_path: Path):
        overlay = tmp_path / "flux2cloud_42.png"
        base = tmp_path / "flux2cloud_42_base.png"
        overlay.touch()
        base.touch()
        new_overlay, new_base = yt_thumb._place_thumb(
            tmp_path, "video", str(overlay), str(base), 2
        )
        assert new_overlay == str((tmp_path / "video_thumb_overlay_2.png").resolve())
        assert new_base == str((tmp_path / "video_thumb_2.png").resolve())
        assert not overlay.exists() and not base.exists()

    def test_overlay_opts_skips_empties(self):
        cmd = yt_thumb._overlay_opts(["image"], fg="white", effect="band", size_pct=120)
        assert cmd == [
            "image",
            "--overlay-fg", "white",
            "--overlay-effect", "band",
            "--overlay-size-pct", "120",
        ]

    def test_extract_video_id(self):
        assert (
            yt_thumb._extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )
        assert yt_thumb._extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert yt_thumb._extract_video_id("") == ""
        assert yt_thumb._extract_video_id("not a url") == ""

    def test_parse_generate_output(self):
        out, base = yt_thumb._parse_generate_output('noise {"path": "/a.png", "base_path": "/b.png"} tail')
        assert (out, base) == ("/a.png", "/b.png")
        assert yt_thumb._parse_generate_output("no json here") == ("", "")

    def test_assert_inside_rejects_escape(self, tmp_path: Path):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            yt_thumb._assert_inside(Path("/etc/passwd"), tmp_path.resolve())
        assert exc.value.status_code == 403


class TestConfigEndpoint:
    def test_config_shape(self, video_dir: Path):
        import asyncio

        body = asyncio.run(yt_thumb.get_config())
        assert body["video_source_path"] == str(video_dir)
        assert body["video_extensions"] == "mp4,mkv,webm"
        assert "overlay_defaults" in body

    def test_list_videos(self, video_dir: Path):
        import asyncio

        body = asyncio.run(yt_thumb.list_videos(path="", extensions=""))
        assert len(body["videos"]) == 1
        assert body["videos"][0]["name"] == "video.mp4"
        assert body["videos"][0]["has_thumbnail"] is False

    def test_list_videos_missing_dir(self, tmp_path: Path):
        import asyncio

        body = asyncio.run(
            yt_thumb.list_videos(path=str(tmp_path / "nope"), extensions="mp4")
        )
        assert body["videos"] == [] and "error" in body

    def test_compose_requires_prompt(self, video_dir: Path):
        import asyncio
        from fastapi import HTTPException

        src = str((video_dir / "video.mp4").resolve())
        with pytest.raises(HTTPException):
            asyncio.run(
                yt_thumb.compose(
                    yt_thumb.ComposeRequest(source=src, prompt="  ", sources=[src])
                )
            )

    async def _run_job_to_end(self, job_id: str, timeout: float = 10.0):
        """Wait for a background job worker to finish (test helper)."""
        import asyncio

        await asyncio.wait_for(yt_thumb._jobs[job_id]["done"].wait(), timeout=timeout)
        return await yt_thumb.job_status(job_id)

    def test_compose_without_sources_is_text_to_image(
        self, video_dir: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Compose with no source images runs plain text-to-image (no -R)."""
        import asyncio

        captured: dict = {}
        fake_out = video_dir / "gen_raw.png"
        fake_out.write_bytes(b"fake-png")

        async def fake_run(job_id: str, cmd: list[str]):
            captured["cmd"] = cmd
            return json.dumps({"path": str(fake_out.resolve())})

        monkeypatch.setattr(yt_thumb, "_run_and_log", fake_run)
        src = str((video_dir / "video.mp4").resolve())

        async def _go():
            body = await yt_thumb.compose(
                yt_thumb.ComposeRequest(source=src, prompt="a scene", sources=[])
            )
            return await self._run_job_to_end(body["job_id"])

        status = asyncio.run(_go())
        assert status["status"] == "done"
        assert status["result"]["thumbnail"].endswith("video_thumb_overlay_1.png")
        assert "-R" not in captured["cmd"]
        assert "--size" in captured["cmd"]

    def test_compose_with_sources_passes_refs(
        self, video_dir: Path, monkeypatch: pytest.MonkeyPatch
    ):
        import asyncio

        ref = video_dir / "face.png"
        ref.write_bytes(b"fake-png")
        captured: dict = {}
        fake_out = video_dir / "gen_raw.png"
        fake_out.write_bytes(b"fake-png")

        async def fake_run(job_id: str, cmd: list[str]):
            captured["cmd"] = cmd
            return json.dumps({"path": str(fake_out.resolve())})

        monkeypatch.setattr(yt_thumb, "_run_and_log", fake_run)
        src = str((video_dir / "video.mp4").resolve())

        async def _go():
            body = await yt_thumb.compose(
                yt_thumb.ComposeRequest(
                    source=src, prompt="use image 0", sources=[str(ref.resolve())]
                )
            )
            return await self._run_job_to_end(body["job_id"])

        status = asyncio.run(_go())
        assert status["status"] == "done"
        assert captured["cmd"].count("-R") == 1
        assert str(ref.resolve()) in captured["cmd"]

    def test_edit_requires_prompt(self, video_dir: Path):
        import asyncio
        from fastapi import HTTPException

        src = str((video_dir / "video.mp4").resolve())
        with pytest.raises(HTTPException):
            asyncio.run(yt_thumb.edit(yt_thumb.EditRequest(source=src, prompt="")))

    def test_overlay_requires_title(self, video_dir: Path):
        import asyncio
        from fastapi import HTTPException

        src = str((video_dir / "video.mp4").resolve())
        with pytest.raises(HTTPException):
            asyncio.run(yt_thumb.overlay(yt_thumb.OverlayRequest(source=src, title=" ")))

    def test_download_escapes_root(self, video_dir: Path):
        import asyncio
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            asyncio.run(yt_thumb.download_file(file="/etc/passwd"))
        assert exc.value.status_code == 403

    def test_meta_roundtrip_shares_long_publish_keys(self, video_dir: Path):
        src = video_dir / "video.mp4"
        yt_thumb._save_meta(src, {"title": "hello"})
        meta = yt_thumb._update_meta_after(
            src, "/t/v_thumb_overlay_1.png", "/t/v_thumb_1.png", 1,
            prompt="a scene", overlay_title="SALE",
        )
        assert meta["title"] == "hello"  # other keys preserved
        assert meta["files"]["thumbnail"] == "/t/v_thumb_overlay_1.png"
        assert meta["files"]["thumbnail_base"] == "/t/v_thumb_1.png"
        assert meta["thumbnail_prompt"] == "a scene"
        assert meta["thumbnail_overlay_title"] == "SALE"
        stored = json.loads((video_dir / "video-long-meta.json").read_text())
        assert stored["thumbnail_version"] == 1


class TestJobs:
    def test_run_and_log_streams_stderr(self):
        """A real subprocess: stderr lines land in the job log live."""
        import asyncio

        async def _go():
            job_id = yt_thumb._new_job("test", "src")
            cmd = [
                sys.executable, "-c",
                "import sys; print('stage-one', file=sys.stderr); "
                "print('stage-two', file=sys.stderr); "
                "print('{\"path\": \"/x.png\"}')",
            ]
            stdout = await yt_thumb._run_and_log(job_id, cmd)
            log = "\n".join(yt_thumb._jobs[job_id]["log"])
            return stdout, log

        stdout, log = asyncio.run(_go())
        assert '{"path": "/x.png"}' in stdout
        assert "stage-one" in log and "stage-two" in log
        assert "exited code=0" in log

    def test_run_and_log_failure_raises_with_tail(self):
        import asyncio

        async def _go():
            job_id = yt_thumb._new_job("test", "src")
            cmd = [
                sys.executable, "-c",
                "import sys; print('boom-detail', file=sys.stderr); "
                "raise SystemExit(3)",
            ]
            with pytest.raises(RuntimeError, match="boom-detail"):
                await yt_thumb._run_and_log(job_id, cmd)

        asyncio.run(_go())

    def test_job_status_unknown_404(self):
        import asyncio
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            asyncio.run(yt_thumb.job_status("nope"))
        assert exc.value.status_code == 404

    def test_job_log_caps(self):
        job_id = yt_thumb._new_job("test", "src")
        for i in range(yt_thumb._JOB_LOG_MAX_LINES + 50):
            yt_thumb._job_log(job_id, f"line {i}")
        assert len(yt_thumb._jobs[job_id]["log"]) == yt_thumb._JOB_LOG_MAX_LINES
        yt_thumb._job_log(job_id, "x" * (yt_thumb._JOB_LOG_MAX_LINE + 100))
        assert len(yt_thumb._jobs[job_id]["log"][-1]) <= yt_thumb._JOB_LOG_MAX_LINE + 1

    def test_worker_error_marks_job(self, video_dir: Path):
        """A failing generate marks the job error (no exception escapes)."""
        import asyncio

        async def boom(job_id: str, cmd: list[str]):
            raise RuntimeError("synthetic failure")

        # Patch the seam indirectly: run a compose worker with a stub runner.
        orig = yt_thumb._run_and_log
        yt_thumb._run_and_log = boom
        try:
            async def _go():
                job_id = yt_thumb._new_job("compose", "src")
                src = str((video_dir / "video.mp4").resolve())
                req = yt_thumb.ComposeRequest(source=src, prompt="x", sources=[])
                await yt_thumb._compose_worker(job_id, req, video_dir / "video.mp4", [])
                return await yt_thumb.job_status(job_id)

            status = asyncio.run(_go())
        finally:
            yt_thumb._run_and_log = orig
        assert status["status"] == "error"
        assert "synthetic failure" in status["error"]
