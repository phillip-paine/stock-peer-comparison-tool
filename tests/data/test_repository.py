from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from peer_comparison_tool.data.models import (
    CompanyInfo,
    DataStorageRecord,
    TickerMostRecentMetric,
    TickerTimeSeries,
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
