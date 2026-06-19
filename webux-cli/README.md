# webux

Modular web UI server for fast-market — one `webux serve` process, multiple plugin tabs.

## Installation

```bash
pip install -e ./webux-cli
```

## First-time setup

Workdir must be configured before using the Files and YT Poster tabs:

```bash
toolsetup workdir init /path/to/your/workdir-root
toolsetup workdir new
```

## CLI Reference

### `webux serve`

Start the web UI server.

```bash
# Default: all interfaces, port 8007
webux serve

# Custom port
webux serve -p 9000

# Open browser automatically on start
webux serve --open

# Kill any existing server on the port, then start
webux serve --restart

# Combined
webux serve -p 8888 --open --restart
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `0.0.0.0` | Bind address |
| `-p`, `--port` | `8007` | Port |
| `--open` | off | Open browser after start |
| `--restart` | off | Kill existing process on port before starting (requires `psutil`) |

### `webux setup`

Manage webux configuration.

```bash
# Show current config as YAML
webux setup show

# Show config file path
webux setup show-path

# Reset config to empty (backs up existing config)
webux setup reset
```

## Tabs

The server starts at `http://localhost:8007` and redirects to the first available tab.

### 📁 Files (`/fileviewer`)

Browse and edit config, data, and workdir files with a CodeMirror editor (Dracula theme).

- **Left sidebar**: expandable tree for `~/.config/fast-market`, `~/.local/share/fast-market`, and `workdir_root`
- **Extension filter**: show only yaml, yml, json, txt, sh, md (customizable, `.bak` hidden by default)
- **Content search**: filter tree to files containing a query string
- **Save**: writes file and creates a `.bak` backup automatically
- **Undo**: restores from the `.bak` backup

API prefix: `/api/fileviewer/`

### 📤 YT Poster (`/yt_poster`)

Review and batch-post YouTube comment replies from JSON batch files.

1. Enter a path relative to workdir (e.g., `replies.json`) and click **Load**
2. Select rows with checkboxes; click **Post selected** to invoke `youtube batch-comment-post`
3. Click **🔄** on a row to regenerate its reply via `prompt batch-apply`
4. Click **✏️** to edit a reply inline and save back to the JSON file
5. Navigate workdir history with **← Prev** / **Last →** buttons

**Input file format**: JSON array. Each object needs at minimum:
- For comments: `comment_text`, `reply` (or `generated_reply`), optionally `video_title`, `channel_name`, `view_count`
- For videos: `transcript`, `reply`, optionally `video_title`

A `.batch-post-report.json` file is written alongside the source file after each post.

API prefix: `/api/yt_poster/`

### ▶ Plan Editor (`/skill_runner`)

View and edit skill plan files (`*.run.yaml`) and their associated skill/prompt files.

1. Select a detected plan from the auto-discovered list (matches `*.run.yaml` in workdir) or enter a URL/path
2. The left panel lists the plan file, referenced skill directories, and associated prompts
3. Edit any file with CodeMirror (Save/Undo supported)
4. Filter by `.bak` visibility or search in file contents

API prefix: `/api/skill_runner/`

### 👁 Monitor (from `monitor-cli`)

If `monitor-cli` is installed, a **Monitor** tab appears automatically, showing trigger logs, running status, and diagnostics. See `monitor-cli/README.md` for details.

## Architecture

```
webux-cli/
├── cli/main.py          # Entry: discovers plugins + commands via entry points
├── core/
│   ├── server.py        # FastAPI app factory, nav injection, lazy mount middleware
│   └── security.py      # _assert_path_safe() — path containment guard
├── commands/
│   ├── serve/           # webux serve command
│   └── setup/           # webux setup group
└── webux/               # Tab plugins (registered via pyproject.toml entry points)
    ├── fileviewer/      # 📁 Files tab — read/write/search config & workdir files
    ├── yt_poster/       # 📤 YT Poster tab — batch post YouTube comments/videos
    └── skill_runner/    # ▶ Plan Editor tab — load run.yaml plans, edit skill files
```

**Plugin discovery**: `pyproject.toml` `[project.entry-points."fast_market.webux_plugins"]`. Each entry point must export `register(config: dict) -> WebuxPluginManifest`.

**Lazy loading**: plugin routers are mounted on first request to `/{name}` or `/api/{name}/...` — startup is fast regardless of plugin count.

## Troubleshooting

### "workdir is not configured" (404)
Run `toolsetup workdir init <path>` then `toolsetup workdir new` to create and activate a workdir.

### Port already in use
Use `--restart`: `webux serve --restart`. This sends SIGTERM to the process on the port.

### Tab does not appear
Reinstall the package after adding plugins: `pip install -e .`. Plugins register via Python entry points — changes to `pyproject.toml` require reinstall.

### `youtube` command not found (yt_poster)
Install `youtube-cli` from the monorepo (`pip install -e ./youtube-cli`) and ensure the venv is activated.

### Reply regeneration fails (yt_poster)
The `prompt batch-apply` command requires `prompt-cli` installed and a valid prompt template. Check `prompt list` and verify the `prompt-name` field in the JSON metadata.

## Development / Testing

```bash
cd webux-cli
pytest tests/ -v
```

See [AGENTS.md](AGENTS.md) for plugin architecture, security rules, and extension points.
