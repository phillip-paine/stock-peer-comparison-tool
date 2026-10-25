"""
Read-only database access for the MCP server.

Separate from `data/database.py` on purpose. That module's `get_engine()` creates
the data directory and `init_db()` creates tables -- both writes. This one opens
the SQLite file in read-only mode (`mode=ro`) plus `PRAGMA query_only`, so even a
bug in a tool cannot modify the data. It never calls `init_db()`.

`NullPool`: every call opens a fresh connection and closes it. SQLite connections
are cheap, and it means the server sees a pipeline refresh (or a replaced
database file) on the very next call instead of holding a stale handle.

SQLite only. Read-only is enforced by how the file is opened, which has no
equivalent for an arbitrary `PCT_DATABASE_URL`, so any other backend is refused
rather than served without that guarantee.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from ..data.config import settings
from .read_repository import ReadRepository

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def database_path() -> Path:
    """Resolve the SQLite file from the same setting the pipeline writes to
    (`PCT_DATABASE_URL` / `PCT_DATA_DIR`), and check it exists."""
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite":
        raise RuntimeError(
            f"The MCP server only supports SQLite (got {url.get_backend_name()!r}): "
            "read-only access is enforced by opening the file read-only."
        )
    if not url.database or url.database == ":memory:":
        raise RuntimeError("The MCP server needs a file-backed SQLite database, not an in-memory one.")
    path = Path(url.database).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(
            f"Database file not found: {path}. Run the pipeline first, or point "
            "PCT_DATABASE_URL / PCT_DATA_DIR at the right place."
        )
    return path


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        path = database_path()

        def _connect() -> sqlite3.Connection:
            conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5.0, check_same_thread=False)
            conn.execute("PRAGMA query_only=ON")
            return conn

        _engine = create_engine("sqlite://", creator=_connect, poolclass=NullPool, future=True)
    return _engine


def check_database() -> Path:
    """Fail fast at startup (clear error on stderr) instead of on the first tool call."""
    get_engine()
    return database_path()


@contextmanager
def read_repository() -> Iterator[ReadRepository]:
    """A `ReadRepository` for one tool call. Never commits; always closes."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    session = _session_factory()
    try:
        yield ReadRepository(session)
    finally:
        session.rollback()
        session.close()
