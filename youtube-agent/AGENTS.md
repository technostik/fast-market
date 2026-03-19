# youtube-agent/

## 🎯 Purpose
Provides a modular CLI interface for YouTube Data API v3 operations with plugin-style command discovery and OAuth authentication.

## 🏗️ Essential Components
- `youtube_entry/__init__.py` — Package entry point exporting main CLI function
- `cli/main.py` — Creates and configures Click CLI group with dynamic command loading
- `core/engine.py` — Factory for building authenticated YouTube clients
- `core/config.py` — Configuration loader for YouTube-specific settings
- `commands/` — Directory containing all CLI commands as discoverable plugins
- `commands/base.py` — Defines `CommandManifest` dataclass for command registration

## 📋 Core Responsibilities
- Provide unified CLI interface for YouTube API operations
- Handle OAuth 2.0 authentication flow and token management
- Track API quota usage across sessions
- Support multiple input formats (JSON, YAML, stdin)
- Enable command composition via UNIX-style pipes
- Maintain XDG-compliant configuration and cache directories

## 🔗 Dependencies & Integration
- Imports from: `common.auth.youtube`, `common.youtube`, `common.cli`, `common.core`
- Used by: End users via CLI, potential GUI wrappers
- External deps: google-api-python-client, google-auth-oauthlib, click, pyyaml, pydantic

## ✅ Do's
- Always use `build_youtube_client()` from engine.py for consistent client creation
- Include `--stdin` flag for commands that can accept piped input
- Support both JSON and YAML input/output formats
- Handle quota limits gracefully with clear error messages
- Use `click.echo` for user output, `click.ClickException` for errors
- Validate configuration before making API calls

## ❌ Don'ts
- Don't hardcode file paths; use `get_tool_config()` from common.core.paths
- Don't bypass OAuth flow; always use `YouTubeOAuth` from common.auth
- Don't ignore quota tracking; always pass quota_limit to YouTubeClient
- Don't modify sys.path manually (already handled in youtube_entry)
- Don't create circular imports between commands

## 🛠️ Extension Points
- To add new command:
  1. Create `commands/your_command/register.py`
  2. Implement `def register(plugin_manifests: dict) -> CommandManifest`
  3. Return decorated click command wrapped in CommandManifest
  4. Command automatically discovered via `discover_commands()`
- To modify API behavior:
  - Extend `YouTubeClient` in `common.youtube.client`
  - Add new models in `common.youtube.models`
- To support additional auth methods:
  - Extend `YouTubeOAuth` in `common.auth.youtube`

## 📚 Related Documentation
- See `common/AGENTS.md` for shared utilities patterns
- See `README.md` for CLI usage examples
- Refer to [Google YouTube API docs](https://developers.google.com/youtube/v3) for API specifics
```
