from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from common import structlog
from common.core.paths import get_tool_data_dir

logger = structlog.get_logger(__name__)

_BACKUP_DIR_NAME = "backups"
_BACKUP_KEEP = 5


def create_sqlite_engine(
    tool_name: str,
    db_filename: str | None = None,
    echo: bool = False,
    db_path: str | Path | None = None,
) -> Engine:
    """Create a standard SQLite engine for any agent."""
    if db_path is None:
        if db_filename is None:
            db_filename = f"{tool_name}.db"
        resolved_path = get_tool_data_dir(tool_name) / db_filename
    else:
        resolved_path = Path(db_path).expanduser()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)

    db_url = f"sqlite+pysqlite:///{resolved_path}"
    logger.info("creating_sqlite_engine", tool=tool_name, path=str(resolved_path))

    return create_engine(
        db_url,
        future=True,
        echo=echo,
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_pre_ping=True,
    )


def create_memory_engine(echo: bool = False) -> Engine:
    """Create an in-memory SQLite engine for testing."""
    logger.info("creating_memory_engine")
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        echo=echo,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        pool_pre_ping=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker:
    """Create a session factory for an engine."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )


@contextmanager
def session_scope(session_factory: sessionmaker) -> Generator[Session, None, None]:
    """Provide a transactional scope for database operations."""
    session: Session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _parse_sqlite_path(db_url: str | None) -> Path | None:
    """Extract the filesystem path from a SQLAlchemy sqlite URL, or None."""
    if not db_url:
        return None
    for prefix in ("sqlite+pysqlite:///", "sqlite:///"):
        if db_url.startswith(prefix):
            raw = db_url[len(prefix):]
            path = Path(raw).expanduser()
            return path if path.name else None
    return None


def backup_sqlite_db(db_path: Path, tool_name: str) -> Path:
    """Create a consistent snapshot of a SQLite database before migration.

    Uses the sqlite3 online backup API so the snapshot is valid even if the
    database is in use. Backups land in ``<db_dir>/backups/`` with a
    ``pre-migration`` timestamp suffix; only the newest ``_BACKUP_KEEP``
    are retained.
    """
    backup_dir = db_path.parent / _BACKUP_DIR_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / f"{db_path.stem}.pre-migration-{stamp}{db_path.suffix}"

    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    backups = sorted(backup_dir.glob(f"{db_path.stem}.pre-migration-*{db_path.suffix}"))
    for stale in backups[: max(0, len(backups) - _BACKUP_KEEP)]:
        stale.unlink()

    logger.info(
        "db_backup_created", tool=tool_name, backup=str(backup_path), count=len(backups)
    )
    return backup_path


def _alembic_at_head(config: "Config", db_path: Path) -> bool:
    """True when the DB is already at the head revision (no migration needed)."""
    from alembic.script import ScriptDirectory

    heads = set(ScriptDirectory.from_config(config).get_heads())
    if not db_path.exists():
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:
            return False
    finally:
        conn.close()
    if row is None:
        return False
    return {row[0]} == heads


def run_alembic_migrations(
    tool_name: str,
    alembic_ini_path: Path,
    db_url_override: str | None = None,
) -> None:
    """Run Alembic migrations for a tool.

    Before migrating an existing file-backed database, a timestamped snapshot
    is written to ``<db_dir>/backups/`` so synced data is never lost if a
    migration fails. No backup is created when the DB is already at head or
    does not exist yet.
    """
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError as exc:
        raise RuntimeError("pip install alembic") from exc

    config = Config(str(alembic_ini_path))
    if db_url_override:
        config.set_main_option("sqlalchemy.url", db_url_override)

    db_path = _parse_sqlite_path(config.get_main_option("sqlalchemy.url"))
    if db_path is not None and db_path.exists():
        if _alembic_at_head(config, db_path):
            logger.info("migrations_up_to_date", tool=tool_name)
            return
        backup_sqlite_db(db_path, tool_name)

    try:
        command.upgrade(config, "head")
        logger.info("migrations_complete", tool=tool_name)
    except Exception as exc:
        if "config" in str(exc).lower() or isinstance(exc, KeyError):
            logger.warning("alembic_context_warning_skipped", tool=tool_name)
            return
        logger.error("migrations_failed", tool=tool_name, error=str(exc))
        raise RuntimeError(f"Database migration failed for {tool_name}") from exc
