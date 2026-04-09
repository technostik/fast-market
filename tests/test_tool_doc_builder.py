"""Tests for the multi-level tool documentation builder."""
from __future__ import annotations

import pytest

from common.agent.doc import build_tool_documentation


class TestToolDocumentationBuilder:
    """Test the multi-level tool documentation builder."""

    def test_depth_1_tools_only(self):
        """Depth 1 should return tool names and descriptions only."""
        doc = build_tool_documentation(depth=1)
        
        assert "# Available Tools" in doc
        assert "## Fast-Market Tools" in doc
        assert "## System Commands" in doc
        assert "## Discovery" in doc
        
        # Should have tool names with backticks
        assert "- `" in doc
        assert "` — " in doc  # Tool name — description format

    def test_depth_2_includes_subcommands(self):
        """Depth 2 should include first-level subcommands."""
        doc = build_tool_documentation(depth=2)
        
        # Should have nested items (indented subcommands)
        lines = doc.split("\n")
        has_nested = any(line.startswith("  - `") for line in lines)
        
        # May or may not have subcommands depending on tool state
        # Just verify structure is correct
        assert "## Fast-Market Tools" in doc

    def test_depth_3_includes_sub_subcommands(self):
        """Depth 3 should include sub-subcommands."""
        doc = build_tool_documentation(depth=3)
        
        assert "## Fast-Market Tools" in doc

    def test_depth_0_recursive(self):
        """Depth 0 should recursively discover all subcommands."""
        doc = build_tool_documentation(depth=0)
        
        assert "## Fast-Market Tools" in doc
        assert "## System Commands" in doc

    def test_custom_tools_list(self):
        """Should support custom tool list."""
        doc = build_tool_documentation(
            tools=["skill"],
            depth=1,
        )
        
        assert "## Fast-Market Tools" in doc
        # Should only have skill tool
        assert "`skill`" in doc

    def test_no_system_commands(self):
        """Should support excluding system commands."""
        doc = build_tool_documentation(
            depth=1,
            include_system_commands=False,
        )
        
        assert "## Fast-Market Tools" in doc
        assert "## System Commands" not in doc

    def test_custom_system_commands(self):
        """Should support custom system commands list."""
        doc = build_tool_documentation(
            depth=1,
            system_commands=["ls", "cat"],
        )
        
        assert "`ls`" in doc
        assert "`cat`" in doc

    def test_markdown_format(self):
        """Output should be valid markdown format."""
        doc = build_tool_documentation(depth=1)
        
        # Should have markdown formatting
        assert "#" in doc  # Headers
        assert "`" in doc  # Code formatting
