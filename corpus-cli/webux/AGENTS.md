# corpus-cli/webux

Webux UI plugins contributed by corpus-cli to the fast-market webux hub.

## Plugins

### corpus/
Tab providing corpus search, browse, and status UI.
Wraps existing corpus API logic — does not duplicate storage or embedding code.
All heavy imports are deferred to handler call time (lazy=True).

## Entry Point
Declared in corpus-cli/pyproject.toml under [project.entry-points."fast_market.webux_plugins"].

## Do's
- Import SQLAlchemyStore, Embedder, etc. inside handler functions, not at module level
- Reuse existing corpus commands/storage — do not reimplement business logic here
- Keep register() side-effect free and fast

## Don'ts
- Don't start background threads or load ML models in register()
- Don't duplicate storage logic from corpus-cli/storage/
