"""Tests for the charisma plugin: folder scanning, job progress/ETA, and the
end-to-end scan -> analyze -> status flow."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from webux.charisma.cache import CACHE_FILENAME, get_cached_entry, load_cache, save_cache_entry
from webux.charisma.models import DEFAULT_EXTENSIONS, FileResult, ScanJob, file_kind
from webux.charisma.register import StartRequest, _scan_folder, scan, start, status

SAMPLE_MP3 = Path(
    "/home/joriel/Code/fast-market/venv/lib/python3.11/site-packages/"
    "gradio/media_assets/audio/cate_blanch.mp3"
)


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


async def _wait_for_job(job_id: str, timeout_iters: int = 60):
    import asyncio

    for _ in range(timeout_iters):
        result = await status(job_id)
        if result["status"] == "done":
            return result
        await asyncio.sleep(0.5)
    pytest.fail("job did not complete in time")


class TestScanAndAnalyzeEndToEnd:
    @pytest.mark.asyncio
    async def test_start_and_poll_status_to_completion(self, tmp_path):
        if not SAMPLE_MP3.exists():
            pytest.skip("sample audio fixture not available in this environment")
        shutil.copy(SAMPLE_MP3, tmp_path / "voice.mp3")

        req = StartRequest(folder=str(tmp_path), extensions="mp3")
        started = await start(req)
        assert started["total"] == 1
        assert started["cached"] == 0
        result = await _wait_for_job(started["job_id"])

        assert result["completed"] == 1
        f = result["files"][0]
        assert f["status"] == "done"
        assert f["cached"] is False
        assert 0.0 <= f["charisma_score"] <= 100.0
        assert "median_f0_hz" in f

    @pytest.mark.asyncio
    async def test_status_unknown_job_404(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await status("does-not-exist")
        assert exc.value.status_code == 404


class TestScoreCache:
    @pytest.mark.asyncio
    async def test_cache_round_trip(self, tmp_path):
        f = tmp_path / "clip.wav"
        f.write_bytes(b"fake audio bytes")

        await save_cache_entry(tmp_path, f, {"charisma_score": 55.5})

        cache = load_cache(tmp_path)
        entry = get_cached_entry(cache, f)
        assert entry is not None
        assert entry["scores"]["charisma_score"] == 55.5
        assert (tmp_path / CACHE_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_cache_invalidated_when_file_changes(self, tmp_path):
        f = tmp_path / "clip.wav"
        f.write_bytes(b"original bytes")
        await save_cache_entry(tmp_path, f, {"charisma_score": 55.5})

        f.write_bytes(b"different bytes, different size")  # mtime + size change

        cache = load_cache(tmp_path)
        assert get_cached_entry(cache, f) is None

    def test_missing_cache_file_returns_empty(self, tmp_path):
        cache = load_cache(tmp_path)
        assert cache["files"] == {}

    @pytest.mark.asyncio
    async def test_second_start_reuses_cache_without_reanalysis(self, tmp_path):
        if not SAMPLE_MP3.exists():
            pytest.skip("sample audio fixture not available in this environment")
        shutil.copy(SAMPLE_MP3, tmp_path / "voice.mp3")

        first = await start(StartRequest(folder=str(tmp_path), extensions="mp3"))
        first_result = await _wait_for_job(first["job_id"])
        first_score = first_result["files"][0]["charisma_score"]

        # Second scan of the same unmodified folder: should resolve entirely from
        # cache, with nothing queued for analysis (job already "done" immediately).
        second = await start(StartRequest(folder=str(tmp_path), extensions="mp3"))
        assert second["cached"] == 1
        second_status = await status(second["job_id"])
        assert second_status["status"] == "done"
        assert second_status["completed"] == 1
        f = second_status["files"][0]
        assert f["cached"] is True
        assert f["charisma_score"] == first_score

    @pytest.mark.asyncio
    async def test_force_recompute_bypasses_cache(self, tmp_path):
        if not SAMPLE_MP3.exists():
            pytest.skip("sample audio fixture not available in this environment")
        shutil.copy(SAMPLE_MP3, tmp_path / "voice.mp3")

        first = await start(StartRequest(folder=str(tmp_path), extensions="mp3"))
        await _wait_for_job(first["job_id"])

        second = await start(StartRequest(folder=str(tmp_path), extensions="mp3", force_recompute=True))
        assert second["cached"] == 0
        second_status = await _wait_for_job(second["job_id"])
        f = second_status["files"][0]
        assert f["cached"] is False
        assert f["status"] == "done"
