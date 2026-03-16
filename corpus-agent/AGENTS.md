# corpus-agent

- Follow DRY, KISS, and fail loudly principles.
- Keep business logic in `core/`, `storage/`, and `plugins/`; CLI/API are thin wrappers.
- Use `structlog` for observability.
- Keep module boundaries clean so directories are removable.
