"""Tests for the command executor, especially heredoc handling."""
from __future__ import annotations

import tempfile
from pathlib import Path

from common.agent.executor import (
    _parse_command_tokens,
    execute_command,
    is_command_allowed,
)


class TestParseCommandTokens:
    """Test command token parsing, especially with heredocs."""

    def test_simple_command(self):
        """Simple commands should parse normally."""
        cmd = "cat file.txt"
        success, tokens, error = _parse_command_tokens(cmd)
        assert success, f"Failed: {error}"
        assert tokens == ["cat", "file.txt"]

    def test_command_with_quotes(self):
        """Commands with quotes should parse normally."""
        cmd = "echo 'hello world'"
        success, tokens, error = _parse_command_tokens(cmd)
        assert success, f"Failed: {error}"
        assert tokens == ["echo", "hello world"]

    def test_heredoc_with_quoted_delimiter(self):
        """Heredoc with quoted delimiter should extract base command."""
        cmd = "cat > scripts/run.sh << 'EOF'"
        success, tokens, error = _parse_command_tokens(cmd)
        assert success, f"Failed to parse heredoc command: {error}"
        assert tokens[0] == "cat"
        assert tokens[1] == ">"
        assert tokens[2] == "scripts/run.sh"

    def test_heredoc_full_multiline(self):
        """Full multiline heredoc command should extract base command."""
        cmd = """cat > scripts/run.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "test"
EOF"""
        success, tokens, error = _parse_command_tokens(cmd)
        assert success, f"Failed to parse full heredoc: {error}"
        assert tokens[0] == "cat"

    def test_heredoc_unquoted_delimiter(self):
        """Heredoc with unquoted delimiter should work."""
        cmd = "cat > file.txt << EOF\ncontent\nEOF"
        success, tokens, error = _parse_command_tokens(cmd)
        assert success, f"Failed to parse unquoted heredoc: {error}"
        assert tokens[0] == "cat"


class TestCommandAllowlist:
    """Test that heredoc commands pass the whitelist check."""

    def test_heredoc_cat_allowed(self):
        """Heredoc with cat should be allowed."""
        cmd = """cat > output.txt << 'EOF'
test content
EOF"""
        allowed = {"cat", "echo", "bash"}
        is_allowed, error = is_command_allowed(cmd, allowed)
        assert is_allowed, f"Command should be allowed: {error}"

    def test_heredoc_bash_allowed(self):
        """Heredoc with bash should be allowed."""
        cmd = """bash << 'SCRIPT'
echo "hello"
SCRIPT"""
        allowed = {"cat", "echo", "bash"}
        is_allowed, error = is_command_allowed(cmd, allowed)
        assert is_allowed, f"Command should be allowed: {error}"

    def test_heredoc_not_allowed(self):
        """Heredoc with non-whitelisted command should be rejected."""
        cmd = """rm -rf / << 'EOF'
EOF"""
        allowed = {"cat", "echo", "bash"}
        is_allowed, error = is_command_allowed(cmd, allowed)
        assert not is_allowed
        assert "rm" in error


class TestExecuteHeredoc:
    """Test actual execution of heredoc commands."""

    def test_execute_simple_heredoc(self):
        """Simple heredoc should execute successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            cmd = """cat > output.txt << 'EOF'
test content here
EOF"""
            allowed = {"cat"}
            result = execute_command(cmd, workdir, allowed)
            
            assert result.exit_code == 0, f"Command failed: {result.stderr}"
            output_file = workdir / "output.txt"
            assert output_file.exists()
            content = output_file.read_text()
            assert "test content here" in content

    def test_execute_heredoc_with_variables(self):
        """Heredoc with shell variables should execute."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            cmd = """cat > script.sh << 'SCRIPT'
#!/usr/bin/env bash
NAME="World"
echo "Hello $NAME"
SCRIPT"""
            allowed = {"cat"}
            result = execute_command(cmd, workdir, allowed)
            
            assert result.exit_code == 0, f"Command failed: {result.stderr}"
            script_file = workdir / "script.sh"
            assert script_file.exists()
            content = script_file.read_text()
            assert "Hello $NAME" in content  # Single quotes prevent expansion

    def test_execute_heredoc_complex_script(self):
        """Complex heredoc script should execute without quotation errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            scripts_dir = workdir / "scripts"
            scripts_dir.mkdir()
            
            cmd = """cat > scripts/run.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Configuration
MAX_VIDEOS="${SKILL_MAX_VIDEOS:-5}"
INPUT_FILE="found_videos.json"
OUTPUT_FILE="best_videos.json"

echo "=== Processing ==="
echo "Max videos: $MAX_VIDEOS"

# Create sample output
echo '{"videos": []}' > "$OUTPUT_FILE"
echo "Done"
EOF"""
            
            allowed = {"cat"}
            result = execute_command(cmd, workdir, allowed)
            
            # Should not get "No closing quotation" error
            assert result.exit_code == 0, f"Command failed: {result.stderr}"
            assert "No closing quotation" not in result.stderr
            
            script_file = scripts_dir / "run.sh"
            assert script_file.exists()
            content = script_file.read_text()
            assert "set -euo pipefail" in content
            assert "MAX_VIDEOS" in content
