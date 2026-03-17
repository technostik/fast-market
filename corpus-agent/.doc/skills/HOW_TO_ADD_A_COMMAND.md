# How to add a new command

## Steps

1. Create `commands/<name>/` with:
   - `__init__.py` (empty)
   - `register.py` — implement `register(plugin_manifests) -> CommandManifest`
   - `AGENTS.md` — describe what the command does and its extension points

2. In `register.py`:
   ```python
   import click
   from commands.base import CommandManifest
   from commands.helpers import build_engine, out

   def register(plugin_manifests: dict) -> CommandManifest:

       @click.command("<name>")
       @click.option("--format", "fmt",
                     type=click.Choice(["json", "text"]), default="text")
       @click.pass_context
       def my_cmd(ctx, fmt, **kwargs):
           engine, plugins, store = build_engine(ctx.obj["verbose"])
           # ... command logic ...
           out(result, fmt)

       # Inject any plugin options for this command
       for pm in plugin_manifests.values():
           my_cmd.params.extend(pm.cli_options.get("<name>", []))

       return CommandManifest(
           name="<name>",
           click_command=my_cmd,
           api_router=_build_router(),  # optional
       )
   ```

3. Add `"commands.<name>"` to `[tool.setuptools] packages` in `pyproject.toml`.

4. Write tests in `tests/test_cli.py` and `tests/test_api.py`.

## What happens automatically

The command is discovered and added to the CLI group on next startup.
Its API router (if any) is included in the FastAPI app.
No changes to `cli/main.py` or `api/server.py`.

## Receiving plugin-contributed options

Use `**kwargs` in the command callback to absorb injected options.
Pass them to `make_filters(**kwargs)` from `commands/helpers.py` if
the command supports filtering.
