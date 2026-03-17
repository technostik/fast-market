from __future__ import annotations

import inspect
import json
import sys

import click
import structlog

from storage.sqlite_store import SearchFilters

logger = structlog.get_logger(__name__)


_SF_PARAMS = set(inspect.signature(SearchFilters.__init__).parameters) - {"self"}


def build_engine(verbose: bool):
    """Construct the SyncEngine, plugins, and store from config. Mirrors _build() in cli/main.py."""
    from core.config import load_config
    from core.embedder import Embedder
    from core.registry import build_plugins
    from core.sync_engine import SyncEngine
    from storage.sqlite_store import SQLiteStore

    _configure_logging(verbose)
    config = load_config()
    store = SQLiteStore(config.get("db_path", ":memory:"))
    embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
    engine = SyncEngine(store, embedder)
    plugins = build_plugins(config)
    return engine, plugins, store


def out(data: object, fmt: str) -> None:
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
        for key, value in data.items():
            if key == "raw_text":
                continue
            click.echo(f"  {key}: {value}")
    else:
        click.echo(str(data))


def fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def make_filters(**kwargs) -> SearchFilters:
    """Build SearchFilters from kwargs, ignoring unrecognized keys."""
    return SearchFilters(**{key: value for key, value in kwargs.items() if key in _SF_PARAMS})


_NOISY_LOGGERS = [
    "core", "storage", "plugins", "sentence_transformers",
    "transformers", "huggingface_hub", "torch", "filelock",
    "urllib3", "httpx",
]


def _configure_logging(verbose: bool) -> None:
    import logging

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
