"""
Engine and session management.

Replaces `data/db.py`. The original `initialize_db_connection`/`close_db`
pair required every caller to remember to close the connection themselves
(several call sites in the original codebase didn't). `session_scope()`
below handles commit/rollback/close automatically via a context manager, so
a failed write can't silently corrupt a shared, unclosed connection.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Lazily create the shared engine. One engine per process — SQLAlchemy
    engines manage their own connection pool, so there's no need (and no
    benefit) to create a new one per call, unlike the original sqlite3.connect()
    calls scattered through db_utils.py.
    """
    global _engine
    if _engine is None:
        settings.ensure_dirs()
        _engine = create_engine(settings.database_url, future=True)
        if _engine.dialect.name == "sqlite":
            # SQLite ignores FOREIGN KEY constraints unless explicitly told
            # to enforce them, per connection. Without this, the FKs declared
            # in models.py (e.g. TickerTimeSeries.ticker -> CompanyInfo.ticker)
            # are decorative only, and a bug that writes ticker-level data
            # before its CompanyInfo row would fail silently instead of
            # raising where the ordering mistake actually happened.
            @event.listens_for(_engine, "connect")
            def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        logger.info("Database engine created for %s", settings.database_url)
    return _engine


def init_db(engine: Engine | None = None) -> None:
    """Create any tables that don't exist yet. This only ever adds tables —
    it never drops them, unlike the original db_tables.py `__main__` block,
    which had `DROP TABLE IF EXISTS` ahead of every CREATE TABLE and relied
    on manually commenting out lines to avoid wiping data.

    Actual schema *changes* (adding/renaming a column) should go through a
    migration tool (e.g. Alembic) rather than this function.
    """
    Base.metadata.create_all(engine or get_engine())


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for a unit of work: commits on success, rolls back
    on any exception, always closes. Use this instead of passing a raw
    connection/cursor around, e.g.:

        with session_scope() as session:
            repo = Repository(session)
            repo.upsert_dataframe(CompanyInfo, df)
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
