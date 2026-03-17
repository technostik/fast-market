from __future__ import annotations

import json
import logging
import sys

import click
import structlog
import uvicorn

from core.config import load_config
from core.embedder import Embedder
from core.registry import build_plugins
from core.sync_engine import SyncEngine
from storage.sqlite_store import SQLiteStore, SearchFilters

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

_NOISY_LOGGERS = [
    "core",
    "storage",
    "plugins",
    "sentence_transformers",
    "transformers",
    "huggingface_hub",
    "torch",
    "filelock",
    "urllib3",
    "httpx",
]


def _configure_logging(verbose: bool) -> None:
    """
    Non-verbose (default): silence everything so stdout is clean JSON.
    Verbose (-v): INFO on stderr, stdout stays clean.
    """
    level = logging.INFO if verbose else logging.CRITICAL
    logging.basicConfig(level=level, stream=sys.stderr,
                        format="%(asctime)s [%(levelname)-8s] %(name)s %(message)s",
                        force=True)
    logging.root.setLevel(level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)

    if not verbose:
        try:
            from tqdm import tqdm
            tqdm.__init__ = _make_silent_tqdm(tqdm.__init__)
        except ImportError:
            pass
        try:
            import transformers
            transformers.logging.set_verbosity_error()
        except (ImportError, AttributeError):
            pass
        try:
            import sentence_transformers.logging as st_log
            st_log.set_verbosity_error()
        except (ImportError, AttributeError):
            pass


def _make_silent_tqdm(original_init):
    def patched(self, *args, **kwargs):
        kwargs["disable"] = True
        original_init(self, *args, **kwargs)
    return patched


# ---------------------------------------------------------------------------
# Output helpers — stdout only, stderr for logs
# ---------------------------------------------------------------------------

def _out(data: object, fmt: str) -> None:
    if fmt == "json":
        click.echo(json.dumps(data, ensure_ascii=False, default=str))
    else:
        _print_text(data)


def _print_text(data: object) -> None:
    if isinstance(data, list):
        for item in data:
            _print_text(item)
            click.echo("")
    elif isinstance(data, dict):
        for k, v in data.items():
            if k == "raw_text":
                continue
            click.echo(f"  {k}: {v}")
    else:
        click.echo(str(data))


def _fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


# ---------------------------------------------------------------------------
# Engine builder
# ---------------------------------------------------------------------------

def _build(verbose: bool) -> tuple[SyncEngine, dict, SQLiteStore]:
    _configure_logging(verbose)
    config = load_config()
    store = SQLiteStore(config.get("db_path", ":memory:"))
    embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
    engine = SyncEngine(store, embedder)
    plugins = build_plugins(config)
    return engine, plugins, store


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show logs on stderr. When off, only result output is printed on stdout.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


@main.command()
@click.pass_context
def setup(ctx: click.Context) -> None:
    """Interactive setup wizard."""
    _configure_logging(ctx.obj["verbose"])
    from setup_wizard import run_wizard
    run_wizard()


@main.command()
@click.option("--source", type=click.Choice(["obsidian", "youtube", "all"]), default="all")
@click.option("--mode", type=click.Choice(["new", "backfill"]), default="new")
@click.option("--limit", type=int, default=None)
@click.option("--clean", is_flag=True, default=False)
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def sync(ctx: click.Context, source: str, mode: str, limit: int | None, clean: bool, fmt: str) -> None:
    """Sync content from sources into the index."""
    engine, plugins, store = _build(ctx.obj["verbose"])
    if clean:
        store.delete_all()
    targets = list(plugins.keys()) if source == "all" else [source]
    results = []
    for name in targets:
        effective_limit = limit if limit is not None else (5 if name == "youtube" else 10)
        result = engine.sync(plugins[name], mode=mode, limit=effective_limit)
        results.append({
            "source": result.source,
            "indexed": result.indexed,
            "skipped": result.skipped,
            "failures": len(result.failures),
            "errors": [{"source_id": f.source_id, "error": f.error} for f in result.failures],
        })
    _out(results, fmt)


@main.command()
@click.option("--source", type=click.Choice(["obsidian", "youtube", "all"]), default="all")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def reindex(ctx: click.Context, source: str, fmt: str) -> None:
    """Rebuild embeddings for already-indexed documents."""
    engine, plugins, _ = _build(ctx.obj["verbose"])
    targets = list(plugins.keys()) if source == "all" else [source]
    results = []
    for name in targets:
        r = engine.reindex(plugins[name])
        results.append({"source": r.source, "documents": r.documents, "chunks": r.chunks})
    _out(results, fmt)


@main.command()
@click.argument("query")
@click.option("--mode", type=click.Choice(["semantic", "keyword"]), default="semantic")
@click.option("--limit", type=int, default=5)
@click.option("--source", type=click.Choice(["obsidian", "youtube"]), default=None)
@click.option("--type", "video_type", type=click.Choice(["short", "long"]), default=None)
@click.option("--min-duration", type=int, default=None)
@click.option("--max-duration", type=int, default=None)
@click.option("--since", default=None, help="YYYY-MM-DD")
@click.option("--until", default=None, help="YYYY-MM-DD")
@click.option("--min-size", type=int, default=None)
@click.option("--max-size", type=int, default=None)
@click.option("--privacy-status",
              type=click.Choice(["public", "unlisted", "private", "unknown"]),
              default=None,
              help="Filter by YouTube privacy status.")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def search(
    ctx: click.Context,
    query: str, mode: str, limit: int,
    source: str | None, video_type: str | None,
    min_duration: int | None, max_duration: int | None,
    since: str | None, until: str | None,
    min_size: int | None, max_size: int | None,
    privacy_status: str | None,
    fmt: str,
) -> None:
    """Search the index.

    \b
    Examples:
      corpus search "landing page" --source youtube --type long --format json
      corpus search "IA" --source youtube --privacy-status public
      corpus search "topic" --format json | jq -r '.[0].handle' | xargs corpus get --what content
    """
    engine, _, store = _build(ctx.obj["verbose"])
    filters = SearchFilters(
        source=source, min_duration=min_duration, max_duration=max_duration,
        video_type=video_type, since=since, until=until,
        min_size=min_size, max_size=max_size,
        privacy_status=privacy_status,
    )
    if mode == "keyword":
        results = store.keyword_search(query, limit, filters)
    else:
        vector = engine.embedder.embed_texts([query])[0][1]
        results = store.semantic_search(vector, limit, filters)

    if fmt == "json":
        _out([{
            "handle": r.handle,
            "source_plugin": r.source_plugin,
            "source_id": r.source_id,
            "title": r.title,
            "score": round(r.score, 4),
            "duration_seconds": r.duration_seconds,
            "privacy_status": r.privacy_status,
            "excerpt": r.excerpt,
        } for r in results], fmt)
    else:
        if not results:
            click.echo("no results")
            return
        for r in results:
            dur = f"  duration={_fmt_duration(r.duration_seconds)}" if r.duration_seconds else ""
            priv = f"  privacy={r.privacy_status}" if r.privacy_status else ""
            click.echo(f"[{r.handle}] {r.title}{dur}{priv}")
            click.echo(f"  score={round(r.score, 4)}  source={r.source_plugin}")
            click.echo(f"  {r.excerpt[:120]}")


@main.command(name="get")
@click.argument("handle")
@click.option("--what", type=click.Choice(["meta", "content", "all"]), default="meta")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def get_doc(ctx: click.Context, handle: str, what: str, fmt: str) -> None:
    """Retrieve a document by handle or source_id.

    \b
    Examples:
      corpus get yt-my-video-a3f2 --what content
      corpus get yt-my-video-a3f2 --what all --format json
    """
    _, _, store = _build(ctx.obj["verbose"])
    doc = store.get_document_by_handle(handle)
    if not doc:
        click.echo(f"not found: {handle}", err=True)
        sys.exit(1)
    if what == "content":
        click.echo(doc["raw_text"])
        return
    if what == "meta":
        _out({k: v for k, v in doc.items() if k != "raw_text"}, fmt)
        return
    if fmt == "json":
        _out(doc, fmt)
    else:
        for k, v in doc.items():
            if k == "raw_text":
                click.echo(f"\n--- content ({len(v)} chars) ---\n")
                click.echo(v)
            else:
                click.echo(f"  {k}: {v}")


@main.command(name="delete")
@click.argument("handle")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def delete_doc(ctx: click.Context, handle: str, fmt: str) -> None:
    """Delete a document by handle or source_id."""
    _, _, store = _build(ctx.obj["verbose"])
    deleted = store.delete_document_by_handle(handle)
    if deleted:
        _out({"deleted": True, "handle": handle}, fmt)
    else:
        click.echo(f"not found: {handle}", err=True)
        sys.exit(1)


@main.command()
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def status(ctx: click.Context, fmt: str) -> None:
    """Show document counts per source."""
    _, _, store = _build(ctx.obj["verbose"])
    _out(store.status(), fmt)


@main.command()
@click.option("--port", type=int, default=8000)
@click.pass_context
def serve(ctx: click.Context, port: int) -> None:
    """Start the HTTP API and frontend."""
    _configure_logging(ctx.obj["verbose"])
    uvicorn.run("api.server:app", host="0.0.0.0", port=port, reload=False)



@main.command()
@click.pass_context
def setconfig(ctx: click.Context) -> None:
    """Interactively edit config.yaml settings.

    \b
    Lets you add or remove obsidian.exclude_dirs entries and other
    config values without editing config.yaml by hand.
    """
    _configure_logging(ctx.obj["verbose"])
    import yaml as _yaml
    from pathlib import Path as _Path

    cfg_path = _Path("config.yaml")
    if not cfg_path.exists():
        raise click.ClickException("config.yaml not found — run 'corpus setup' first")

    config = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    click.echo("=== corpus setconfig ===")
    click.echo("Press Enter to keep current value. Type a new value to change it.")
    click.echo("")

    # --- obsidian.exclude_dirs ---
    ob_cfg = config.setdefault("obsidian", {})
    current_excludes: list[str] = list(ob_cfg.get("exclude_dirs") or [])
    built_in = {".obsidian", ".trash", ".git"}
    click.echo(f"obsidian.exclude_dirs (built-in: {sorted(built_in)})")
    click.echo(f"  current extra excludes: {current_excludes or '(none)'}")
    click.echo("  Enter comma-separated directory names to EXCLUDE (e.g. Templates,Archive).")
    click.echo("  Enter '-' to clear all extra excludes.")
    raw = click.prompt("  exclude_dirs", default=",".join(current_excludes) if current_excludes else "", show_default=False).strip()
    if raw == "-":
        ob_cfg["exclude_dirs"] = []
        click.echo("  → cleared")
    elif raw:
        new_excludes = [d.strip() for d in raw.split(",") if d.strip()]
        ob_cfg["exclude_dirs"] = new_excludes
        click.echo(f"  → {new_excludes}")
    else:
        click.echo("  → unchanged")

    click.echo("")

    # --- embed_batch_size ---
    current_batch = config.get("embed_batch_size", 32)
    raw = click.prompt(f"embed_batch_size", default=str(current_batch)).strip()
    try:
        config["embed_batch_size"] = int(raw)
    except ValueError:
        click.echo("  invalid integer, keeping current value")

    click.echo("")

    # --- youtube.index_non_public ---
    yt_cfg = config.setdefault("youtube", {})
    current_inp = bool(yt_cfg.get("index_non_public", False))
    raw = click.prompt(f"youtube.index_non_public (true/false)", default=str(current_inp).lower()).strip().lower()
    yt_cfg["index_non_public"] = raw in ("true", "1", "yes")

    click.echo("")
    cfg_path.write_text(_yaml.dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    click.echo(f"Saved to {cfg_path}")

    # Show the resulting exclude list (built-in + configured)
    all_excludes = sorted(built_in | set(ob_cfg.get("exclude_dirs") or []))
    click.echo(f"Effective obsidian exclude_dirs: {all_excludes}")


if __name__ == "__main__":
    main()
