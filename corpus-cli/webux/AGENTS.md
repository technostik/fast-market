# corpus-cli/webux

Webux UI plugins contributed by corpus-cli to the fast-market webux hub.

## Plugins

### corpus/
Tab providing basic corpus search, list, and status UI.
Wraps existing corpus API logic — does not duplicate storage or embedding code.
All heavy imports are deferred to handler call time (lazy=True).

### corpus_browser/
Advanced corpus browser with filtering, sorting, and content preview.
Provides bird's eye view of indexed content for content creation workflows.
Supports keyword/semantic search with advanced filters (source, date range, duration).
Displays full transcripts/markdown with title and description on click.
Reuses existing corpus storage and search logic.

## Entry Point
Declared in corpus-cli/pyproject.toml under [project.entry-points."fast_market.webux_plugins"].

## Do's
- Import SQLAlchemyStore, Embedder, etc. inside handler functions, not at module level
- Reuse existing corpus commands/storage — do not reimplement business logic here
- Keep register() side-effect free and fast

## Don'ts
- Don't start background threads or load ML models in register()
- Don't duplicate storage logic from corpus-cli/storage/
