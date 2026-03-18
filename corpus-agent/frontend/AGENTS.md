# corpus-agent/ui

## 🎯 Purpose
Provides a clean, minimal local web interface for interacting with the corpus knowledge index, enabling users to browse, search, and manage indexed documents from Obsidian and YouTube sources without requiring API familiarity.

## 🏗️ Essential Components
- `index.html` — Landing page with navigation cards and live status summary of indexed documents
- `items.html` — Browse interface with filtering by source, document preview modal, and delete functionality
- `search.html` — Search interface supporting both semantic and keyword modes with result previews
- `status.html` — Summary dashboard showing document counts and total video duration by source

## 📋 Core Responsibilities
- Display real-time corpus statistics via `/items?limit=1000` endpoint
- Provide source-filtered browsing of all indexed documents
- Support semantic and keyword search with unified result presentation
- Render document previews with source-appropriate formatting (Markdown for Obsidian, plain text for YouTube)
- Enable document deletion directly from UI with confirmation
- Maintain consistent visual language across all pages (DM Mono/Syne fonts, dark theme, source color-coding)
- Load dynamic frontend fragments via `/api/frontend-fragments` for extensibility

## 🔗 Dependencies & Integration
- Imports from: Backend API endpoints (`/items`, `/search`, `/document/{plugin}/{id}`, `/api/frontend-fragments`)
- Used by: Browser clients accessing `/ui/*` routes
- External deps: Google Fonts (DM Mono, Syne), browser native fetch API

## ✅ Do's
- Keep UI purely presentational — all data comes from backend API calls
- Use consistent source color coding: `var(--obsidian)` for Obsidian, `var(--youtube)` for YouTube
- Implement modal previews with proper markdown rendering for Obsidian notes
- Show loading states and graceful error messages when API calls fail
- Include delete confirmation dialogs before destructive actions
- Use `encodeURIComponent` for all dynamic path segments in API URLs
- Preserve source-specific URLs: Obsidian URIs for notes, YouTube links for videos

## ❌ Don'ts
- Don't hardcode document counts or status — always fetch fresh from API
- Don't implement complex markdown parsers — keep renderer minimal and safe (escaping HTML)
- Don't assume API availability — always handle fetch errors
- Don't mix inline JavaScript with complex logic — keep event handlers simple and readable
- Don't use external JavaScript libraries — vanilla JS only
- Don't expose API keys or sensitive data in frontend code

## 🛠️ Extension Points
- To add new source type: Add color variable in `:root`, update source badge logic in each page, add filter button in items.html, update status display
- To modify preview rendering: Extend `renderMarkdown()` function with additional markdown patterns
- To add new UI fragment: Backend can inject via `/api/frontend-fragments` — scripts will be appended to document head
- To change search behavior: Update fetch URL parameters in `doSearch()` function
- To add bulk operations: Extend items.html with selection checkboxes and batch delete endpoint

## 📚 Related Documentation
- See `API.md` for available endpoints and response formats
- Refer to `GOLDEN_RULES.md` for core principles (DRY, KISS, FAIL LOUDLY)
- See Obsidian URI scheme: `obsidian://open?vault={vault}&file={file}`
