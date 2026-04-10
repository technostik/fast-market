"""Tests for batch-reply --filter option."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from commands.batch_reply.register import register


@pytest.fixture
def sample_comments():
    """Sample comment data for testing."""
    return [
        {
            "id": "comment_001",
            "text": "Great video!",
            "author": "User1",
            "video_url": "https://youtube.com/watch?v=abc",
        },
        {
            "id": "comment_002",
            "text": "Thanks for sharing!",
            "author": "User2",
            "video_url": "https://youtube.com/watch?v=abc",
        },
        {
            "id": "comment_003",
            "text": "Very helpful!",
            "author": "User3",
            "video_url": "https://youtube.com/watch?v=def",
        },
    ]


@pytest.fixture
def input_file(tmp_path, sample_comments):
    """Create a temporary input file with sample comments."""
    file_path = tmp_path / "comments.json"
    file_path.write_text(json.dumps(sample_comments))
    return file_path


@pytest.fixture
def mock_llm_setup():
    """Mock LLM provider and config loading."""
    with patch("commands.batch_reply.register.load_tool_config") as mock_config, \
         patch("commands.batch_reply.register.discover_providers") as mock_discover, \
         patch("commands.batch_reply.register.get_default_provider_name") as mock_default:
        
        mock_config.return_value = {"llm": {"default_provider": "test_provider"}}
        mock_default.return_value = "test_provider"
        
        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Test reply"
        mock_provider.complete.return_value = mock_response
        
        mock_discover.return_value = {"test_provider": mock_provider}
        
        yield mock_provider


class TestBatchReplyFilter:
    """Tests for the --filter option in batch-reply command."""

    def test_filter_single_comment_id(self, tmp_path, sample_comments, mock_llm_setup):
        """Test filtering to process only one comment by ID."""
        input_file = tmp_path / "comments.json"
        input_file.write_text(json.dumps(sample_comments))

        cmd_manifest = register({})
        runner = CliRunner()
        
        result = runner.invoke(
            cmd_manifest.click_command,
            [
                str(input_file),
                "-p", "Write a reply",
                "--filter", '["comment_001"]',
            ],
        )
        
        assert result.exit_code == 0
        # Only one comment should be processed
        assert "[1/1]" in result.output
        assert "Filtered to 1 comments matching filter IDs" in result.output

    def test_filter_multiple_comment_ids(self, tmp_path, sample_comments, mock_llm_setup):
        """Test filtering to process multiple comments by IDs."""
        input_file = tmp_path / "comments.json"
        input_file.write_text(json.dumps(sample_comments))

        cmd_manifest = register({})
        runner = CliRunner()
        
        result = runner.invoke(
            cmd_manifest.click_command,
            [
                str(input_file),
                "-p", "Write a reply",
                "--filter", '["comment_001", "comment_003"]',
            ],
        )
        
        assert result.exit_code == 0
        # Two comments should be processed
        assert "[1/2]" in result.output
        assert "[2/2]" in result.output
        assert "Filtered to 2 comments matching filter IDs" in result.output

    def test_filter_with_non_matching_ids(self, tmp_path, sample_comments, mock_llm_setup):
        """Test filter with IDs that don't match any comments."""
        input_file = tmp_path / "comments.json"
        input_file.write_text(json.dumps(sample_comments))

        cmd_manifest = register({})
        runner = CliRunner()
        
        result = runner.invoke(
            cmd_manifest.click_command,
            [
                str(input_file),
                "-p", "Write a reply",
                "--filter", '["nonexistent_id"]',
            ],
        )
        
        assert result.exit_code == 0
        # No comments should be processed
        assert "Filtered to 0 comments matching filter IDs" in result.output

    def test_filter_invalid_json(self, tmp_path, sample_comments):
        """Test filter with invalid JSON raises an error."""
        input_file = tmp_path / "comments.json"
        input_file.write_text(json.dumps(sample_comments))

        cmd_manifest = register({})
        runner = CliRunner()
        
        result = runner.invoke(
            cmd_manifest.click_command,
            [
                str(input_file),
                "-p", "Write a reply",
                "--filter", 'not valid json',
            ],
        )
        
        assert "invalid JSON" in result.output

    def test_filter_not_a_list(self, tmp_path, sample_comments):
        """Test filter with JSON that is not a list."""
        input_file = tmp_path / "comments.json"
        input_file.write_text(json.dumps(sample_comments))

        cmd_manifest = register({})
        runner = CliRunner()
        
        result = runner.invoke(
            cmd_manifest.click_command,
            [
                str(input_file),
                "-p", "Write a reply",
                "--filter", '{"id": "comment_001"}',
            ],
        )
        
        assert "must be a JSON list" in result.output

    def test_filter_works_with_other_options(self, tmp_path, sample_comments, mock_llm_setup):
        """Test that filter works in addition to other options like --output."""
        input_file = tmp_path / "comments.json"
        input_file.write_text(json.dumps(sample_comments))
        output_file = tmp_path / "output.json"

        cmd_manifest = register({})
        runner = CliRunner()
        
        result = runner.invoke(
            cmd_manifest.click_command,
            [
                str(input_file),
                "-p", "Write a reply",
                "--filter", '["comment_002"]',
                "-o", str(output_file),
            ],
        )
        
        assert result.exit_code == 0
        assert output_file.exists()
        
        # Verify output contains only filtered comment
        output_data = json.loads(output_file.read_text())
        assert len(output_data) == 1
        assert output_data[0]["original_comment"]["id"] == "comment_002"
