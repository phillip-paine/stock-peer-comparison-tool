"""
The few extra reads the MCP tools need on top of `Repository`.

Same pattern as `PortfolioRepository`: a subclass, so the generic
`fetch_dataframe()` / `latest_cluster_membership()` /
`recent_metrics_by_subindustry()` are reused as-is. Everything here is a read.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Type

import pandas as pd
from sqlalchemy import func, select

from ..data.models import Base
from ..data.repository import Repository


class ReadRepository(Repository):
    def max_date(self, model: Type[Base], date_column: str = "date") -> date | None:
        """Latest value of a date column, or None for an empty table."""
        column = getattr(model, date_column)
        value = self._session.execute(select(func.max(column))).scalar_one_or_none()
        return _as_date(value)

    def row_count(self, model: Type[Base]) -> int:
        return int(self._session.execute(select(func.count()).select_from(model)).scalar_one())

    def recent_rows(self, model: Type[Base], n: int, **equality_filters: Any) -> pd.DataFrame:
        """The latest `n` rows by `date` (oldest first), for an exact-match filter.

        Filters on the key (e.g. one ticker), so the frame read is one entity's
        history, not a whole table. `date` is coerced to datetime64 straight
        away: SQLite hands back Python `date` objects (object dtype), which
        sort fine but turn into mixed dtypes the moment anything is merged or
        concatenated with date-range-derived data.
        """
        df = self.fetch_dataframe(model, **equality_filters)
        if df.empty:
            return df
        df = df.assign(date=pd.to_datetime(df["date"])).sort_values("date")
        return df.tail(n).reset_index(drop=True)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()
