"""
Repository layer: every read or write to the data store goes through here.

Replaces `data/db_utils.py` and `data/queries.py`. Key differences from the
original:

- No SQL built by string formatting (the original `f"SELECT * FROM {table}"`
  and `f"...WHERE ticker = '{ticker}'"` patterns are gone — everything below
  goes through the SQLAlchemy expression layer, which parameterizes values
  automatically).
- One generic `upsert()` replaces both `insert_or_replace()` and
  `insert_or_ignore()`. Those functions built their column list and
  conflict target from whatever the caller's DataFrame happened to contain;
  here the primary key is read directly off the ORM model, so a DataFrame
  with a missing or extra column can't silently produce the wrong SQL.
- `check_ticker_data_recency()` and `check_asset_data_recency()` — which
  were identical except for the staleness threshold — collapse into one
  `is_data_recent(ticker, max_age_days)`.
- NaN values are converted to NULL before insert. The original passed
  DataFrame values straight to sqlite3, which is a common source of "nan"
  being stored as a literal string instead of NULL.
- Dates are native Python `date` objects throughout, handled by SQLAlchemy's
  type system. This removes the need for `unix_to_date_format()`, which
  existed only because `DataFrame.to_sql()` had silently stored dates as
  unix-nanosecond integers in the original code.

`insert_quarterly_data()` from the original db_utils.py is not carried
forward: it referenced a `quarterly_reports` table with columns (`eps`,
`revenue`, `net_income`) that don't match any table this schema defines
(the real table is `quarterly_financial_data`) and isn't called anywhere
in the traced data codepath — it looks like dead code from an earlier
schema version.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Literal, Type

import pandas as pd
from sqlalchemy import inspect, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import Base, ClusterMembership, CompanyInfo, DataStorageRecord, TickerMostRecentMetric

UpsertMode = Literal["ignore", "replace"]


class Repository:
    """Wraps a SQLAlchemy Session with the read/write operations the data
    pipeline needs. Callers never see a Session, Connection, or raw SQL —
    only models, DataFrames, and plain Python values.
    """

    def __init__(self, session: Session):
        self._session = session

    # ---- writes -------------------------------------------------------

    def upsert(
            self,
            model: Type[Base],
            records: Iterable[dict[str, Any]],
            mode: UpsertMode = "ignore",
    ) -> int:
        """Insert rows, skipping (`mode="ignore"`) or overwriting
        (`mode="replace"`) any that collide on the model's primary key.

        Returns the number of records submitted (not necessarily the number
        actually written, since "ignore" mode may skip some on conflict).
        """
        cleaned = [_clean_record(r) for r in records]
        if not cleaned:
            return 0

        table = model.__table__
        pk_cols = [c.name for c in inspect(model).primary_key]
        # No `.values(cleaned)` here: that would inline every row into ONE
        # multi-row INSERT whose bound-parameter count grows with the batch
        # (rows x columns), and SQLite rejects a statement with more than
        # SQLITE_MAX_VARIABLE_NUMBER parameters (999 on old builds, 32766 on
        # stock 3.32+, 250000 on Debian/Ubuntu) with "too many SQL
        # variables". Passing the records as the execute() parameter list
        # instead runs it as an executemany: one small statement, many
        # parameter sets, so batch size no longer matters.
        stmt = sqlite_insert(table)

        update_cols = {c.name: stmt.excluded[c.name] for c in table.columns if c.name not in pk_cols}

        if mode == "ignore":
            stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)
        elif mode == "replace":
            if update_cols:
                stmt = stmt.on_conflict_do_update(index_elements=pk_cols, set_=update_cols)
            else:
                # Every column is part of the primary key (e.g. DataStorageRecord),
                # so there's nothing to overwrite — falling back to do_nothing is
                # equivalent to "replace" here, since a conflicting row would be
                # byte-for-byte identical anyway.
                stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)
        else:
            raise ValueError(f"Unknown upsert mode: {mode!r}")

        self._session.execute(stmt, cleaned)
        return len(cleaned)

    def upsert_dataframe(
            self,
            model: Type[Base],
            df: pd.DataFrame,
            mode: UpsertMode = "ignore",
    ) -> int:
        """Same as `upsert()`, but takes a DataFrame whose columns are
        expected to match the model's *attribute* names (e.g. `asset_class`),
        which is how every transform function in this codebase names its
        output columns -- not necessarily the underlying DB column name,
        which can differ for a column declared with a custom
        `mapped_column("SomeName")`. In this schema that's just
        `AssetClassTimeSeries.asset_class`, mapped to the DB column
        `"AssetClass"`.

        This distinction matters more than it looks: SQLAlchemy Core's
        `insert().values()` (used inside `upsert()`) requires dict keys to
        match the DB column name, not the ORM attribute name -- verified
        directly, passing `{"asset_class": ...}` raises `CompileError:
        Unconsumed column names: asset_class` rather than translating it.
        The previous version of this method filtered DataFrame columns
        against `model.__table__.columns` (DB names), so `asset_class`
        never matched anything and was silently dropped before the record
        dicts were even built -- no exception, no warning. Every row this
        pipeline has ever written to `asset_class_time_series` has had a
        NULL `AssetClass` column as a result. Existing rows need a one-time
        backfill (a straight `UPDATE ... SET "AssetClass" = ...` per asset
        class, not a re-fetch from yfinance); this fix only prevents the
        same thing happening to future writes.

        Columns the model doesn't recognize are dropped rather than
        raising, so upstream transform code can pass a slightly wider frame
        without needing to hand-curate a column list at every call site
        (the original `data/main.py` did this manually, e.g.
        `recent_metrics_table_keys`).
        """
        if df.empty:
            return 0
        attr_to_db_name = {prop.key: prop.columns[0].name for prop in inspect(model).column_attrs}
        df = df[[c for c in df.columns if c in attr_to_db_name]]
        records = [{attr_to_db_name[k]: v for k, v in record.items()} for record in df.to_dict("records")]
        return self.upsert(model, records, mode=mode)

    def record_fetch(self, tickers: Iterable[str], as_of: date | None = None) -> None:
        """Stamp today's date (or `as_of`) as the last-fetched date for each
        ticker/asset. Replaces the repeated `record_data_saved = pd.DataFrame(...)`
        blocks in `data/main.py` and `db_utils.update_other_asset_classes`.
        """
        as_of = as_of or date.today()
        records = [{"ticker": t, "version_date": as_of} for t in tickers]
        self.upsert(DataStorageRecord, records, mode="replace")

    # ---- recency checks -------------------------------------------------

    def is_data_recent(self, ticker: str, max_age_days: int) -> bool:
        """True if the most recent fetch for `ticker` is within `max_age_days`.

        Replaces `check_ticker_data_recency` (14-day threshold) and
        `check_asset_data_recency` (same-day threshold) — those two
        functions were identical apart from the hardcoded cutoff, so the
        threshold is now a parameter instead of a second copy of the query.
        """
        stmt = (
            select(DataStorageRecord.version_date)
            .where(DataStorageRecord.ticker == ticker)
            .order_by(DataStorageRecord.version_date.desc())
            .limit(1)
        )
        latest = self._session.execute(stmt).scalar_one_or_none()
        if latest is None:
            return False
        return latest >= date.today() - timedelta(days=max_age_days)

    # ---- reads ----------------------------------------------------------

    def fetch_dataframe(
            self,
            model: Type[Base],
            since: date | None = None,
            **equality_filters: Any,
    ) -> pd.DataFrame:
        """Read rows from `model`'s table into a DataFrame, optionally
        filtered by exact-match columns (e.g. `ticker="AAPL"`) and/or a
        minimum `date`.

        Replaces `fetch_table_data()`, which built its query from an
        f-string table name and had a special-cased, hardcoded reference to
        `cluster_table` inside a `most_recent` branch that only one caller
        actually used.
        """
        stmt = select(model)
        for column, value in equality_filters.items():
            stmt = stmt.where(getattr(model, column) == value)
        if since is not None and hasattr(model, "date"):
            stmt = stmt.where(model.date >= since)
        # Read through the session's own connection (not session.bind, which
        # would open a separate connection) so this sees writes made earlier
        # in the same uncommitted transaction — needed when several
        # refresh_*() calls run back-to-back inside one session_scope(),
        # as aggregations.run_all() does.
        df = pd.read_sql(stmt, self._session.connection())
        # Return ORM *attribute* names, mirroring `upsert_dataframe` (which
        # takes them). They only differ where a column was declared with an
        # explicit DB name -- today just `AssetClassTimeSeries.asset_class`,
        # stored as "AssetClass". Without this, a frame written with one
        # spelling comes back with the other, and anything keyed on the
        # attribute name (e.g. the Market Conditions transform) hits KeyError.
        db_to_attr = {
            prop.columns[0].name: prop.key
            for prop in inspect(model).column_attrs
            if prop.columns[0].name != prop.key
        }
        return df.rename(columns=db_to_attr) if db_to_attr else df

    def latest_cluster_membership(self) -> pd.DataFrame:
        """Most recent DBSCAN cluster-membership row per ticker.

        `cluster_table` accumulates one row per ticker *per pipeline run*
        (clustering, once it exists, will write with `mode="ignore"` like
        everything else in `aggregations.py`), so historical assignments
        pile up rather than being overwritten. This replaces the old
        `fetch_table_data(..., most_recent=True)` branch that special-cased
        `cluster_table` by grouping on ticker and keeping the max date —
        same tie-breaking behaviour (latest `date` wins per ticker), just
        expressed as a normal Repository method instead of a hardcoded
        branch inside the generic fetch function.
        """
        all_rows = self.fetch_dataframe(ClusterMembership)
        if all_rows.empty:
            return all_rows
        latest_idx = all_rows.groupby("ticker")["date"].idxmax()
        return all_rows.loc[latest_idx].reset_index(drop=True)

    def recent_metrics_by_subindustry(self, sub_industry: str) -> pd.DataFrame:
        """Latest valuation metrics for every ticker in a sub-industry,
        joined against `company_info`. Feeds the DBSCAN valuation-cluster
        step. Replaces the `recent_metrics_sector_query` raw SQL string.
        """
        stmt = (
            select(TickerMostRecentMetric, CompanyInfo.sub_industry)
            .join(CompanyInfo, CompanyInfo.ticker == TickerMostRecentMetric.ticker)
            .where(CompanyInfo.sub_industry == sub_industry)
        )
        return pd.read_sql(stmt, self._session.connection())


def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
    """Convert NaN (and pandas NaT) to None so sqlite stores NULL rather than
    a literal 'nan' string or raising a type error at insert time.
    """
    return {k: (None if _is_missing(v) else v) for k, v in record.items()}


def _is_missing(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        # pd.isna() raises for some array-like types we don't expect here;
        # treat anything it can't judge as present, not missing.
        return False