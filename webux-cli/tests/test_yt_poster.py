"""Tests for yt_poster plugin save_reply endpoint."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Add webux-cli to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.yt_poster.plugin import router


@pytest.fixture
def app():
    """Create a FastAPI app with the yt_poster router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def sample_data():
    """Sample data for testing."""
    return [
        {
            "video_url": "https://youtube.com/watch?v=abc",
            "original_comment": {
                "id": "comment_001",
                "text": "Great video!",
                "author": "User1",
            },
            "reply": "Original reply",
            "generated_reply": "Original reply",
        },
        {
            "video_url": "https://youtube.com/watch?v=def",
            "original_comment": {
                "id": "comment_002",
                "text": "Thanks!",
                "author": "User2",
            },
            "reply": "Another reply",
            "generated_reply": "Another reply",
        },
    ]


@pytest.fixture
def workdir(tmp_path, sample_data):
    """Create a temporary workdir with sample data file."""
    data_file = tmp_path / "test_data.json"
    data_file.write_text(json.dumps(sample_data))
    return tmp_path


class TestSaveReply:
    """Tests for the save_reply endpoint."""

    def test_save_reply_success(self, client, workdir, sample_data):
        """Test successfully saving an edited reply."""
        with patch("plugins.yt_poster.plugin._workdir", return_value=workdir):
            response = client.post(
                "/save_reply",
                json={
                    "file": "test_data.json",
                    "index": 0,
                    "reply": "Edited reply text",
                },
            )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        # Verify the file was updated
        updated_data = json.loads((workdir / "test_data.json").read_text())
        assert updated_data[0]["reply"] == "Edited reply text"
        assert updated_data[0]["generated_reply"] == "Edited reply text"

    def test_save_reply_file_not_found(self, client, workdir):
        """Test saving reply when file doesn't exist."""
        with patch("plugins.yt_poster.plugin._workdir", return_value=workdir):
            response = client.post(
                "/save_reply",
                json={
                    "file": "nonexistent.json",
                    "index": 0,
                    "reply": "Some reply",
                },
            )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_save_reply_index_out_of_range(self, client, workdir, sample_data):
        """Test saving reply with invalid index."""
        with patch("plugins.yt_poster.plugin._workdir", return_value=workdir):
            response = client.post(
                "/save_reply",
                json={
                    "file": "test_data.json",
                    "index": 99,
                    "reply": "Some reply",
                },
            )

        assert response.status_code == 404
        assert "out of range" in response.json()["detail"].lower()

    def test_save_reply_negative_index(self, client, workdir, sample_data):
        """Test saving reply with negative index."""
        with patch("plugins.yt_poster.plugin._workdir", return_value=workdir):
            response = client.post(
                "/save_reply",
                json={
                    "file": "test_data.json",
                    "index": -1,
                    "reply": "Some reply",
                },
            )

        assert response.status_code == 404

    def test_save_reply_updates_both_fields(self, client, workdir, sample_data):
        """Test that saving updates both 'reply' and 'generated_reply' fields."""
        with patch("plugins.yt_poster.plugin._workdir", return_value=workdir):
            response = client.post(
                "/save_reply",
                json={
                    "file": "test_data.json",
                    "index": 1,
                    "reply": "Updated reply",
                },
            )

        assert response.status_code == 200

        updated_data = json.loads((workdir / "test_data.json").read_text())
        assert updated_data[1]["reply"] == "Updated reply"
        assert updated_data[1]["generated_reply"] == "Updated reply"
