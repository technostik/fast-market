Looking at `server.py`, I can see this is a FastAPI server that serves both frontend HTML pages and API endpoints for the corpus-agent system. Here are the comprehensive AI agent guidelines:

# server

## 🎯 Purpose
Serves the HTTP interface for corpus-agent, providing both frontend HTML pages and API endpoints for plugin/command discovery and execution.

## 🏗️ Essential Components
- `server.py` — Main FastAPI application that configures routes, serves static frontend files, and dynamically loads plugin/command API routers
- `_FRONTEND` — Path resolution to frontend static files (HTML pages)
- `_html()` — Helper function that reads and returns HTML files with proper error handling
- `frontend_fragments()` — API endpoint that returns JavaScript fragments from plugins and commands
- `_load()` — Dynamic loader that discovers and registers API routers from plugins and commands

## 📋 Core Responsibilities
- Serve frontend HTML pages (`/ui`, `/ui/items`, `/ui/search`, `/ui/status`)
- Provide API endpoints for frontend JavaScript fragment discovery
- Dynamically load and register API routers from discovered plugins and commands
- Handle 404 errors for missing frontend files gracefully
- Redirect root path `/` to `/ui` for better UX

## 🔗 Dependencies & Integration
- Imports from: `core.config`, `core.registry`, `fastapi`
- Used by: Frontend HTML pages (via browser), plugins and commands (via API router registration)
- External deps: `fastapi` (web framework), `structlog` (implied from AGENTS.md), `pathlib` (path handling)

## ✅ Do's
- Keep route definitions explicit and minimal (use loops only for truly repetitive patterns)
- Use helper functions like `_html()` to encapsulate file reading logic
- Fail loudly with explicit HTTPExceptions when files are missing
- Follow FastAPI best practices for response type annotations
- Load plugins and commands dynamically at startup via `_load()`

## ❌ Don'ts
- Don't hardcode frontend paths — always resolve relative to `__file__`
- Don't catch and hide exceptions from file reading — let FastAPI handle them
- Don't modify frontend files through the API — this server is read-only for static files
- Don't block startup if a plugin fails to load — use explicit exceptions but let others continue

## 🛠️ Extension Points
- To add new frontend page: Add new tuple to the route list with path and HTML filename
- To add new API endpoint: Create a plugin or command with `api_router` attribute
- To modify frontend fragment discovery: Extend the data structure returned by `frontend_fragments()`
- To add middleware/authentication: Extend FastAPI app before `_load()` is called

## 📚 Related Documentation
- See `core/registry.md` for plugin/command discovery mechanism
- See `frontend/README.md` for frontend HTML page structure
- Refer to `AGENTS.md` in project root for overall system architecture
