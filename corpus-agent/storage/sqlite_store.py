from __future__ import annotations

import warnings

from storage.sqlalchemy_store import SQLAlchemyStore, SearchFilters


class SQLiteStore(SQLAlchemyStore):
    def __init__(self, path: str | None = None) -> None:
        warnings.warn(
            "SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(path)


__all__ = ["SQLiteStore", "SearchFilters"]
