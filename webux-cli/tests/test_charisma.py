"""Tests for the charisma plugin: folder scanning, job progress/ETA, and the
end-to-end scan -> analyze -> status flow."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from webux.charisma.models import DEFAULT_EXTENSIONS, FileResult, ScanJob, file_kind
from webux.charisma.register import StartRequest, _scan_folder, scan, start, status


class TestFileKind:
    def test_video_extension(self):
        assert file_kind(".mp4") == "video"
        assert file_kind("mkv") == "video"

    def test_audio_extension(self):
        assert file_kind(".mp3") == "audio"
        assert file_kind("wav") == "audio"


class TestFileResultToDict:
    def test_pending_has_no_scores(self):
        fr = FileResult(path="/tmp/a.wav", name="a.wav", kind="audio")
        d = fr.to_dict()
        assert d["status"] == "pending"
        assert "charisma_score" not in d

    def test_done_merges_scores(self):
        fr = FileResult(
            path="/tmp/a.wav", name="a.wav", kind="audio", status="done",
            scores={"charisma_score": 72.5, "notes": "strengths: pitch variation"},
        )
        d = fr.to_dict()
        assert d["charisma_score"] == 72.5
        assert d["notes"] == "strengths: pitch variation"
        assert d["name"] == "a.wav"

    def test_error_carries_message(self):
        fr = FileResult(path="/tmp/a.wav", name="a.wav", kind="audio", status="error", error="boom")
        d = fr.to_dict()
        assert d["status"] == "error"
        assert d["error"] == "boom"


class TestScanJobToDict:
    def test_empty_job_is_done(self):
        job = ScanJob(job_id="j1", folder="/tmp", files=[])
        job.status = "done"
        d = job.to_dict()
        assert d["total"] == 0
        assert d["progress"] == 100.0

    def test_progress_reflects_completed_count(self):
        job = ScanJob(
            job_id="j1", folder="/tmp",
            files=[
                FileResult(path="/tmp/a.wav", name="a.wav", kind="audio", status="done", scores={"charisma_score": 1}),
                FileResult(path="/tmp/b.wav", name="b.wav", kind="audio", status="pending"),
            ],
        )
        d = job.to_dict()
        assert d["completed"] == 1
        assert d["total"] == 2
        assert d["progress"] == 50.0

    def test_errored_file_counts_as_completed(self):
        job = ScanJob(
            job_id="j1", folder="/tmp",
            files=[FileResult(path="/tmp/a.wav", name="a.wav", kind="audio", status="error", error="x")],
        )
        d = job.to_dict()
        assert d["completed"] == 1
        assert d["progress"] == 100.0


class TestScanFolder:
    def test_lists_matching_extensions_only(self, tmp_path):
        (tmp_path / "clip.mp4").write_bytes(b"x")
        (tmp_path / "voice.wav").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")

        files = _scan_folder(str(tmp_path), "mp4,wav")
        names = sorted(f.name for f in files)
        assert names == ["clip.mp4", "voice.wav"]

    def test_missing_folder_raises_400(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _scan_folder("/tmp/does_not_exist_charisma_xyz", DEFAULT_EXTENSIONS)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_scan_endpoint_returns_kind(self, tmp_path):
        (tmp_path / "clip.mp4").write_bytes(b"x")
        (tmp_path / "voice.wav").write_bytes(b"x")

        result = await scan(path=str(tmp_path), extensions="mp4,wav")
        kinds = {f["name"]: f["kind"] for f in result["files"]}
        assert kinds["clip.mp4"] == "video"
        assert kinds["voice.wav"] == "audio"


class TestScanAndAnalyzeEndToEnd:
    @pytest.mark.asyncio
    async def test_start_and_poll_status_to_completion(self, tmp_path):
        sample = Path(
            "/home/joriel/Code/fast-market/venv/lib/python3.11/site-packages/"
            "gradio/media_assets/audio/cate_blanch.mp3"
        )
        if not sample.exists():
            pytest.skip("sample audio fixture not available in this environment")
        shutil.copy(sample, tmp_path / "voice.mp3")

        req = StartRequest(folder=str(tmp_path), extensions="mp3")
        started = await start(req)
        assert started["total"] == 1
        job_id = started["job_id"]

        import asyncio
        for _ in range(60):
            result = await status(job_id)
            if result["status"] == "done":
                break
            await asyncio.sleep(0.5)
        else:
            pytest.fail("job did not complete in time")

        assert result["completed"] == 1
        f = result["files"][0]
        assert f["status"] == "done"
        assert 0.0 <= f["charisma_score"] <= 100.0
        assert "median_f0_hz" in f

    @pytest.mark.asyncio
    async def test_status_unknown_job_404(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await status("does-not-exist")
        assert exc.value.status_code == 404
