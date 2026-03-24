# commands/embed_server

Manage the persistent embedding server lifecycle.

## Responsibilities
- Start server in background process
- Stop server gracefully
- Show health status
- Restart server

## Operational rules
- Track process with PID file in tool cache
- Remove stale PID file when process is dead
- Prefer graceful shutdown before SIGKILL
- Keep command behavior explicit and fail loudly
