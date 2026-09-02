from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from peer_comparison_tool.data.models import Base


@pytest.fixture()
def session():
    """A fresh, isolated in-memory SQLite session for each test.

    Uses StaticPool so all connections share the same in-memory database
    (plain :memory: would otherwise hand out a new, empty database per
    connection, which breaks Session's connection checkout/checkin).

    Foreign key enforcement is turned on to match production (see
    database.py) — otherwise tests wouldn't catch an insert-order bug that
    writes dependent rows before their CompanyInfo row exists.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()
