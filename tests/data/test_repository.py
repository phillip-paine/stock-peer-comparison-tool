from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from peer_comparison_tool.data.models import (
    AssetClassTimeSeries,
    CompanyInfo,
    DataStorageRecord,
    TickerMostRecentMetric,
    TickerTimeSeries,
    TickerTimeSeriesYoY,
)
from peer_comparison_tool.data.repository import Repository


def _make_company(session, ticker="AAPL", sub_industry="Tech Hardware"):
    session.add(CompanyInfo(ticker=ticker, name=f"{ticker} Inc.", sector="Technology",
                             industry="Hardware", sub_industry=sub_industry))
    session.commit()


class TestUpsert:
    def test_ignore_mode_skips_conflicting_rows(self, session):
        repo = Repository(session)
        _make_company(session)

        repo.upsert(TickerTimeSeries, [
            {"ticker": "AAPL", "date": date(2026, 1, 1), "close_price": 100.0, "close_price_indexed": 100.0},
        ])
        session.commit()

        # Same PK (ticker, date) with a different price — should be ignored.
        repo.upsert(TickerTimeSeries, [
            {"ticker": "AAPL", "date": date(2026, 1, 1), "close_price": 999.0, "close_price_indexed": 999.0},
        ])
        session.commit()

        df = repo.fetch_dataframe(TickerTimeSeries)
        assert len(df) == 1
        assert df.iloc[0]["close_price"] == 100.0

    def test_replace_mode_overwrites_conflicting_rows(self, session):
        repo = Repository(session)
        _make_company(session)

        repo.upsert(TickerTimeSeries, [
            {"ticker": "AAPL", "date": date(2026, 1, 1), "close_price": 100.0, "close_price_indexed": 100.0},
        ], mode="replace")
        session.commit()

        repo.upsert(TickerTimeSeries, [
            {"ticker": "AAPL", "date": date(2026, 1, 1), "close_price": 999.0, "close_price_indexed": 999.0},
        ], mode="replace")
        session.commit()

        df = repo.fetch_dataframe(TickerTimeSeries)
        assert len(df) == 1
        assert df.iloc[0]["close_price"] == 999.0

    def test_upsert_converts_nan_to_null(self, session):
        repo = Repository(session)
        _make_company(session)

        repo.upsert(TickerTimeSeries, [
            {"ticker": "AAPL", "date": date(2026, 1, 1), "close_price": np.nan, "close_price_indexed": 100.0},
        ])
        session.commit()

        df = repo.fetch_dataframe(TickerTimeSeries)
        assert pd.isna(df.iloc[0]["close_price"])

    @pytest.mark.parametrize("mode", ["ignore", "replace"])
    def test_upsert_large_batch_stays_under_sqlite_variable_limit(self, session, mode):
        """Regression: `upsert()` used to build ONE multi-row INSERT for the
        whole batch, so bound parameters scaled with row count. A year of
        daily YoY rows across the full ticker universe (~63k rows x 4 cols,
        ~250k parameters) hit SQLite's `too many SQL variables` limit
        (SQLITE_MAX_VARIABLE_NUMBER: 999 on old builds, 32766 on stock
        3.32+, 250000 on Debian/Ubuntu builds). Earlier tests only used a
        handful of rows, so it never surfaced until real data.

        Asserts on the size of each executed statement rather than on
        whether this machine's SQLite happens to raise, so the test fails
        the same way on every build."""
        from sqlalchemy import event

        _make_company(session)
        repo = Repository(session)
        start = date(2020, 1, 1)
        n_rows = 20_000  # x 4 columns = 80k parameters if sent as one statement
        records = [
            {"ticker": "AAPL", "date": start + timedelta(days=i),
             "close_price_yoy": float(i), "close_price_indexed_yoy": float(i)}
            for i in range(n_rows)
        ]

        params_per_statement: list[int] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            if "ticker_ts_yoy" in statement and statement.lstrip().upper().startswith("INSERT"):
                params_per_statement.append(len(parameters[0]) if executemany else len(parameters))

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", _record)
        try:
            assert repo.upsert(TickerTimeSeriesYoY, records, mode=mode) == n_rows
            assert session.query(TickerTimeSeriesYoY).count() == n_rows

            changed = [{**r, "close_price_yoy": -1.0} for r in records]
            repo.upsert(TickerTimeSeriesYoY, changed, mode=mode)
        finally:
            event.remove(engine, "before_cursor_execute", _record)

        assert params_per_statement, "expected INSERT statements to be captured"
        assert max(params_per_statement) <= 999, (
            f"a single statement bound {max(params_per_statement)} parameters; SQLite's limit is as low as 999"
        )
        assert session.query(TickerTimeSeriesYoY).count() == n_rows
        sample = session.get(TickerTimeSeriesYoY, ("AAPL", start + timedelta(days=n_rows - 1)))
        assert sample.close_price_yoy == (-1.0 if mode == "replace" else float(n_rows - 1))

    def test_upsert_empty_records_is_a_noop(self, session):
        repo = Repository(session)
        assert repo.upsert(TickerTimeSeries, []) == 0

    def test_unknown_mode_raises(self, session):
        repo = Repository(session)
        with pytest.raises(ValueError):
            repo.upsert(TickerTimeSeries, [{"ticker": "AAPL", "date": date(2026, 1, 1)}], mode="bogus")


class TestUpsertDataframe:
    def test_drops_columns_not_on_the_model(self, session):
        repo = Repository(session)
        _make_company(session)

        df = pd.DataFrame([
            {"ticker": "AAPL", "date": date(2026, 1, 1), "close_price": 100.0,
             "close_price_indexed": 100.0, "some_extra_column_from_upstream": "junk"},
        ])
        written = repo.upsert_dataframe(TickerTimeSeries, df)
        session.commit()

        assert written == 1
        result = repo.fetch_dataframe(TickerTimeSeries)
        assert "some_extra_column_from_upstream" not in result.columns

    def test_empty_dataframe_is_a_noop(self, session):
        repo = Repository(session)
        assert repo.upsert_dataframe(TickerTimeSeries, pd.DataFrame()) == 0


class TestRecency:
    def test_no_record_means_not_recent(self, session):
        repo = Repository(session)
        assert repo.is_data_recent("AAPL", max_age_days=14) is False

    def test_recent_record_is_recent(self, session):
        repo = Repository(session)
        repo.record_fetch(["AAPL"], as_of=date.today())
        session.commit()
        assert repo.is_data_recent("AAPL", max_age_days=14) is True

    def test_stale_record_is_not_recent(self, session):
        repo = Repository(session)
        repo.record_fetch(["AAPL"], as_of=date.today() - timedelta(days=30))
        session.commit()
        assert repo.is_data_recent("AAPL", max_age_days=14) is False

    def test_boundary_is_inclusive(self, session):
        repo = Repository(session)
        repo.record_fetch(["AAPL"], as_of=date.today() - timedelta(days=14))
        session.commit()
        assert repo.is_data_recent("AAPL", max_age_days=14) is True

    def test_record_fetch_upserts_multiple_tickers_and_updates_existing(self, session):
        repo = Repository(session)
        repo.record_fetch(["AAPL", "MSFT"], as_of=date.today() - timedelta(days=30))
        session.commit()
        assert repo.is_data_recent("AAPL", max_age_days=14) is False

        # re-recording should overwrite (mode="replace"), not conflict-ignore
        repo.record_fetch(["AAPL", "MSFT"], as_of=date.today())
        session.commit()
        assert repo.is_data_recent("AAPL", max_age_days=14) is True
        assert repo.is_data_recent("MSFT", max_age_days=14) is True


class TestFetchDataframe:
    def test_filters_by_equality(self, session):
        repo = Repository(session)
        _make_company(session, ticker="AAPL")
        _make_company(session, ticker="MSFT")
        repo.upsert(TickerTimeSeries, [
            {"ticker": "AAPL", "date": date(2026, 1, 1), "close_price": 100.0, "close_price_indexed": 100.0},
            {"ticker": "MSFT", "date": date(2026, 1, 1), "close_price": 200.0, "close_price_indexed": 100.0},
        ])
        session.commit()

        df = repo.fetch_dataframe(TickerTimeSeries, ticker="AAPL")
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "AAPL"

    def test_filters_by_since_date(self, session):
        repo = Repository(session)
        _make_company(session)
        repo.upsert(TickerTimeSeries, [
            {"ticker": "AAPL", "date": date(2026, 1, 1), "close_price": 100.0, "close_price_indexed": 100.0},
            {"ticker": "AAPL", "date": date(2026, 6, 1), "close_price": 110.0, "close_price_indexed": 110.0},
        ])
        session.commit()

        df = repo.fetch_dataframe(TickerTimeSeries, since=date(2026, 3, 1))
        assert len(df) == 1
        assert str(df.iloc[0]["date"]) == "2026-06-01"

    def test_returns_orm_attribute_names_not_db_column_names(self, session):
        """Regression: `AssetClassTimeSeries.asset_class` is stored in a DB
        column named "AssetClass". `fetch_dataframe` used to hand back the DB
        name, so a frame written with `upsert_dataframe` (attribute names in)
        came back with a different spelling (DB names out) -- the Market
        Conditions page's `g["asset_class"]` raised KeyError. Reads now mirror
        writes: attribute names both ways."""
        repo = Repository(session)
        repo.upsert_dataframe(AssetClassTimeSeries, pd.DataFrame([{
            "ticker": "Gold", "date": date(2026, 1, 1), "asset_class": "commodity",
            "close_price": 2000.0, "close_price_indexed": 100.0, "close_price_yoy": 1.0,
        }]))
        session.commit()

        df = repo.fetch_dataframe(AssetClassTimeSeries)
        assert "asset_class" in df.columns
        assert "AssetClass" not in df.columns
        assert df.iloc[0]["asset_class"] == "commodity"

    def test_attribute_name_filter_matches_returned_column_name(self, session):
        repo = Repository(session)
        repo.upsert_dataframe(AssetClassTimeSeries, pd.DataFrame([
            {"ticker": "Gold", "date": date(2026, 1, 1), "asset_class": "commodity", "close_price": 1.0},
            {"ticker": "EURUSD", "date": date(2026, 1, 1), "asset_class": "fx", "close_price": 1.0},
        ]))
        session.commit()
        df = repo.fetch_dataframe(AssetClassTimeSeries, asset_class="fx")
        assert list(df["ticker"]) == ["EURUSD"]

    def test_since_is_ignored_for_models_without_a_date_column(self, session):
        repo = Repository(session)
        _make_company(session)
        # CompanyInfo has no `date` column — passing `since` shouldn't raise.
        df = repo.fetch_dataframe(CompanyInfo, since=date(2026, 1, 1))
        assert len(df) == 1


class TestRecentMetricsBySubindustry:
    def test_joins_company_info_and_filters_by_subindustry(self, session):
        repo = Repository(session)
        _make_company(session, ticker="AAPL", sub_industry="Tech Hardware")
        _make_company(session, ticker="JPM", sub_industry="Banks")

        session.add_all([
            TickerMostRecentMetric(ticker="AAPL", market_cap=3_000_000, price_eps_ratio=30.0,
                                    price_to_book=40.0, return_on_equity=1.5, debt_to_equity_ratio=1.5,
                                    profit_margin=0.25, enterprise_to_ebitda=22.0, latest_eps=6.0,
                                    enterprise_value=3_100_000),
            TickerMostRecentMetric(ticker="JPM", market_cap=500_000, price_eps_ratio=12.0,
                                    price_to_book=2.0, return_on_equity=0.15, debt_to_equity_ratio=2.0,
                                    profit_margin=0.3, enterprise_to_ebitda=None, latest_eps=15.0,
                                    enterprise_value=None),
        ])
        session.commit()

        df = repo.recent_metrics_by_subindustry("Tech Hardware")
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "AAPL"
