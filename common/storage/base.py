from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from common import structlog
from common.core.paths import get_tool_data_dir

logger = structlog.get_logger(__name__)


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


def run_alembic_migrations(
    tool_name: str,
    alembic_ini_path: Path,
    db_url_override: str | None = None,
) -> None:
    """Run Alembic migrations for a tool."""
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError as exc:
        raise RuntimeError("pip install alembic") from exc

    config = Config(str(alembic_ini_path))
    if db_url_override:
        config.set_main_option("sqlalchemy.url", db_url_override)

    try:
        command.upgrade(config, "head")
        logger.info("migrations_complete", tool=tool_name)
    except Exception as exc:
        if "config" in str(exc).lower() or isinstance(exc, KeyError):
            logger.warning("alembic_context_warning_skipped", tool=tool_name)
            return
        logger.error("migrations_failed", tool=tool_name, error=str(exc))
        raise RuntimeError(f"Database migration failed for {tool_name}") from exc
