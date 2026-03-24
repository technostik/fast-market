from __future__ import annotations

import inspect
import sys
from pathlib import Path

from common import structlog

from common.cli.helpers import out
from storage.sqlite_store import SearchFilters

logger = structlog.get_logger(__name__)
_TOOL_ROOT = Path(__file__).resolve().parents[1]


_SF_PARAMS = set(inspect.signature(SearchFilters.__init__).parameters) - {"self"}


def build_engine(verbose: bool):
    """Construct the SyncEngine, plugins, and store from config."""
    from common.core.config import load_config
    from common.core.registry import build_plugins
    from core.embedder import Embedder
    from core.sync_engine import SyncEngine
    from storage.sqlite_store import SQLiteStore

    _configure_logging(verbose)
    config = load_config()
    store = SQLiteStore(config.get("db_path"))
    embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
    engine = SyncEngine(store, embedder)
    plugins = build_plugins(config, tool_root=_TOOL_ROOT)
    return engine, plugins, store


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

    try:
        from common import structlog as _structlog

        _structlog.configure(
            wrapper_class=_structlog.make_filtering_bound_logger(level),
            logger_factory=_structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    except Exception:
        pass

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
