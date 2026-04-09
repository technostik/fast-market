"""Tests for prompt_processor module."""

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from commands.batch_reply.prompt_processor import (
    PromptProcessorError,
    apply_template_variables,
    process_prompts,
    read_file_content,
    resolve_file_references,
)


class TestReadFileContent:
    """Tests for read_file_content function."""

    def test_read_actual_file(self, tmp_path):
        """Test reading from an actual file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")
        
        content = read_file_content(str(test_file))
        assert content == "Hello, World!"

    def test_read_from_stdin(self):
        """Test reading from stdin."""
        test_input = "piped content from stdin"
        
        with patch('sys.stdin', StringIO(test_input)):
            content = read_file_content('-')
            assert content == test_input

    def test_empty_stdin_raises_error(self):
        """Test that empty stdin raises an error."""
        with patch('sys.stdin', StringIO('')):
            with pytest.raises(PromptProcessorError, match="No data received from stdin"):
                read_file_content('-')

    def test_nonexistent_file_raises_error(self):
        """Test that a non-existent file raises an error."""
        with pytest.raises(PromptProcessorError, match="File not found"):
            read_file_content('/nonexistent/file.txt')

    def test_directory_raises_error(self, tmp_path):
        """Test that a directory raises an error."""
        with pytest.raises(PromptProcessorError, match="Not a file"):
            read_file_content(str(tmp_path))

    def test_relative_path_resolves_from_working_dir(self, tmp_path):
        """Test that relative paths are resolved from working_dir."""
        test_file = tmp_path / "subdir" / "file.txt"
        test_file.parent.mkdir()
        test_file.write_text("relative content")
        
        content = read_file_content("subdir/file.txt", working_dir=tmp_path)
        assert content == "relative content"

    def test_relative_path_resolves_from_cwd(self, tmp_path, monkeypatch):
        """Test that relative paths are resolved from cwd if no working_dir."""
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "file.txt"
        test_file.write_text("cwd content")
        
        content = read_file_content("file.txt")
        assert content == "cwd content"


class TestResolveFileReferences:
    """Tests for resolve_file_references function."""

    def test_no_file_references(self):
        """Test prompt with no file references."""
        prompt = "Just a simple prompt without any file references"
        result = resolve_file_references(prompt)
        assert result == prompt

    def test_single_file_reference(self, tmp_path):
        """Test resolving a single file reference."""
        test_file = tmp_path / "context.txt"
        test_file.write_text("This is the file content")
        
        prompt = f"Use this context: @{test_file}"
        result = resolve_file_references(prompt, working_dir=tmp_path)
        assert result == "Use this context: This is the file content"

    def test_multiple_file_references(self, tmp_path):
        """Test resolving multiple file references."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")
        
        prompt = f"First: @{file1}\nSecond: @{file2}"
        result = resolve_file_references(prompt, working_dir=tmp_path)
        assert result == "First: content1\nSecond: content2"

    def test_stdin_reference(self):
        """Test resolving @- reference for stdin."""
        test_input = "stdin content"
        
        with patch('sys.stdin', StringIO(test_input)):
            prompt = "Data from stdin: @-"
            result = resolve_file_references(prompt)
            assert result == "Data from stdin: stdin content"

    def test_nonexistent_file_raises_error(self):
        """Test that non-existent file reference raises error."""
        prompt = "Use this: @nonexistent.txt"
        with pytest.raises(PromptProcessorError, match="File not found"):
            resolve_file_references(prompt)


class TestApplyTemplateVariables:
    """Tests for apply_template_variables function."""

    def test_url_variable(self):
        """Test {URL} variable substitution."""
        prompt = "Check out my video: {URL}"
        data = {"video_url": "https://youtube.com/watch?v=123"}
        result = apply_template_variables(prompt, data)
        assert result == "Check out my video: https://youtube.com/watch?v=123"

    def test_author_variable(self):
        """Test {AUTHOR} variable substitution."""
        prompt = "Reply to {AUTHOR}"
        data = {"author": "John Doe"}
        result = apply_template_variables(prompt, data)
        assert result == "Reply to John Doe"

    def test_comment_variable(self):
        """Test {COMMENT} variable substitution."""
        prompt = "Regarding your comment: {COMMENT}"
        data = {"text": "Great video!"}
        result = apply_template_variables(prompt, data)
        assert result == "Regarding your comment: Great video!"

    def test_multiple_variables(self):
        """Test multiple variable substitutions."""
        prompt = "Hi {AUTHOR}, check {URL}"
        data = {
            "author": "Alice",
            "video_url": "https://example.com/video",
        }
        result = apply_template_variables(prompt, data)
        assert result == "Hi Alice, check https://example.com/video"

    def test_missing_variable_empty_string(self):
        """Test that missing variables are replaced with empty string."""
        prompt = "Video: {VIDEO_TITLE}"
        data = {"author": "Bob"}
        result = apply_template_variables(prompt, data)
        assert result == "Video: "

    def test_all_supported_variables(self):
        """Test all supported template variables."""
        data = {
            "video_url": "https://youtube.com/v1",
            "video_id": "abc123",
            "author": "TestUser",
            "text": "Nice video!",
            "video_title": "My Video",
        }
        
        prompt = "{URL} {VIDEO_URL} {VIDEO_ID} {AUTHOR} {COMMENT_AUTHOR} {COMMENT} {COMMENT_TEXT} {VIDEO_TITLE}"
        result = apply_template_variables(prompt, data)
        expected = "https://youtube.com/v1 https://youtube.com/v1 abc123 TestUser TestUser Nice video! Nice video! My Video"
        assert result == expected


class TestProcessPrompts:
    """Tests for process_prompts function."""

    def test_single_prompt(self):
        """Test processing a single prompt."""
        prompts = ["Write a reply"]
        data = {"author": "Alice"}
        result = process_prompts(prompts, data)
        assert result == "Write a reply"

    def test_multiple_prompts_concatenated(self):
        """Test that multiple prompts are concatenated."""
        prompts = ["First instruction", "Second instruction"]
        data = {}
        result = process_prompts(prompts, data)
        assert "\n\n---\n\n" in result
        assert "First instruction" in result
        assert "Second instruction" in result

    def test_file_reference_in_prompt(self, tmp_path):
        """Test file reference processing."""
        test_file = tmp_path / "transcript.txt"
        test_file.write_text("Video transcript content")
        
        prompts = [f"Use this transcript: @{test_file}"]
        data = {}
        result = process_prompts(prompts, data, working_dir=tmp_path)
        assert "Video transcript content" in result

    def test_template_variable_substitution(self):
        """Test template variable processing."""
        prompts = ["Promote video: {URL} to {AUTHOR}"]
        data = {
            "video_url": "https://youtube.com/v1",
            "author": "Bob",
        }
        result = process_prompts(prompts, data)
        assert result == "Promote video: https://youtube.com/v1 to Bob"

    def test_combined_processing(self, tmp_path):
        """Test file references and template variables together."""
        test_file = tmp_path / "context.txt"
        test_file.write_text("Context: be friendly")
        
        prompts = [
            f"Context: @{test_file}",
            "Reply to {AUTHOR} about {URL}",
        ]
        data = {
            "author": "Charlie",
            "video_url": "https://youtube.com/v1",
        }
        result = process_prompts(prompts, data, working_dir=tmp_path)
        
        assert "Context: Context: be friendly" in result
        assert "Reply to Charlie about https://youtube.com/v1" in result

    def test_empty_prompts_raises_error(self):
        """Test that empty prompts raise an error."""
        with pytest.raises(PromptProcessorError, match="No prompts provided"):
            process_prompts([], {})

    def test_stdin_in_prompt(self):
        """Test stdin reference in prompt."""
        test_input = "stdin transcript data"
        
        with patch('sys.stdin', StringIO(test_input)):
            prompts = ["Data: @-"]
            data = {}
            result = process_prompts(prompts, data)
            assert "Data: stdin transcript data" in result
