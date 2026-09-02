from __future__ import annotations

from datetime import date

import pytest

from peer_comparison_tool.data.aggregations import (
    refresh_industry_metrics,
    refresh_industry_metrics_yoy,
    refresh_industry_price_series,
    refresh_industry_price_yoy,
    refresh_ticker_metric_yoy,
    refresh_ticker_price_yoy,
    refresh_valuation_clusters,
    run_all,
)
from peer_comparison_tool.data.models import (
    ClusterMembership,
    CompanyInfo,
    IndustryMetrics,
    IndustryMetricsYoY,
    IndustryTimeSeries,
    IndustryTimeSeriesYoY,
    QuarterlyFinancialData,
    QuarterlyFinancialDataYoY,
    TickerMostRecentMetric,
    TickerTimeSeries,
    TickerTimeSeriesYoY,
)
from peer_comparison_tool.data.repository import Repository


def _seed_companies(repo, session):
    session.add_all([
        CompanyInfo(ticker="AAPL", name="Apple Inc.", sector="Technology",
                    industry="Hardware", sub_industry="Tech Hardware"),
        CompanyInfo(ticker="MSFT", name="Microsoft Corp.", sector="Technology",
                    industry="Software", sub_industry="Tech Hardware"),
    ])
    session.commit()


def _seed_prices(repo, session):
    repo.upsert(TickerTimeSeries, [
        {"ticker": "AAPL", "date": date(2025, 6, 1), "close_price": 100.0, "close_price_indexed": 100.0},
        {"ticker": "AAPL", "date": date(2026, 6, 1), "close_price": 150.0, "close_price_indexed": 150.0},
        {"ticker": "MSFT", "date": date(2025, 6, 1), "close_price": 200.0, "close_price_indexed": 100.0},
        {"ticker": "MSFT", "date": date(2026, 6, 1), "close_price": 220.0, "close_price_indexed": 110.0},
    ])
    session.commit()


def _seed_quarterlies(repo, session):
    repo.upsert(QuarterlyFinancialData, [
        {"ticker": "AAPL", "date": date(2025, 3, 15), "quarter_reporting": "2025_1",
         "basic_eps": 1.0, "operating_income": 10.0, "operating_income_mm": 0.01,
         "net_income": 8.0, "net_income_mm": 0.008, "gross_margin": 40.0,
         "operating_margin": 20.0, "net_margin": 15.0, "ebitda_margin": 25.0},
        {"ticker": "AAPL", "date": date(2026, 3, 20), "quarter_reporting": "2026_1",
         "basic_eps": 1.5, "operating_income": 15.0, "operating_income_mm": 0.015,
         "net_income": 12.0, "net_income_mm": 0.012, "gross_margin": 42.0,
         "operating_margin": 22.0, "net_margin": 16.0, "ebitda_margin": 26.0},
        {"ticker": "MSFT", "date": date(2025, 3, 15), "quarter_reporting": "2025_1",
         "basic_eps": 2.0, "operating_income": 20.0, "operating_income_mm": 0.02,
         "net_income": 16.0, "net_income_mm": 0.016, "gross_margin": 50.0,
         "operating_margin": 30.0, "net_margin": 25.0, "ebitda_margin": 35.0},
        {"ticker": "MSFT", "date": date(2026, 3, 20), "quarter_reporting": "2026_1",
         "basic_eps": 2.2, "operating_income": 22.0, "operating_income_mm": 0.022,
         "net_income": 17.6, "net_income_mm": 0.0176, "gross_margin": 52.0,
         "operating_margin": 31.0, "net_margin": 26.0, "ebitda_margin": 36.0},
    ])
    session.commit()


def _seed_recent_metrics(repo, session, ticker="AAPL", **overrides):
    defaults = dict(
        ticker=ticker, market_cap=1_000_000.0, price_eps_ratio=20.0, price_to_book=5.0,
        return_on_equity=0.2, debt_to_equity_ratio=1.0, profit_margin=0.2,
        enterprise_to_ebitda=15.0, latest_eps=5.0, enterprise_value=1_100_000.0,
    )
    defaults.update(overrides)
    session.add(TickerMostRecentMetric(**defaults))
    session.commit()


class TestRefreshTickerPriceYoy:
    def test_writes_correct_yoy_rows(self, session):
        repo = Repository(session)
        _seed_companies(repo, session)
        _seed_prices(repo, session)

        written = refresh_ticker_price_yoy(repo)
        session.commit()

        assert written == 2
        df = repo.fetch_dataframe(TickerTimeSeriesYoY, ticker="AAPL")
        assert df.iloc[0]["close_price_yoy"] == pytest.approx(50.0)


class TestRefreshTickerMetricYoy:
    def test_writes_correct_yoy_rows(self, session):
        repo = Repository(session)
        _seed_companies(repo, session)
        _seed_quarterlies(repo, session)

        written = refresh_ticker_metric_yoy(repo)
        session.commit()

        assert written == 2
        df = repo.fetch_dataframe(QuarterlyFinancialDataYoY, ticker="AAPL")
        assert df.iloc[0]["basic_eps_yoy"] == pytest.approx(50.0)


class TestRefreshIndustryPriceSeries:
    def test_sums_across_tickers_in_the_same_subindustry(self, session):
        repo = Repository(session)
        _seed_companies(repo, session)
        _seed_prices(repo, session)

        written = refresh_industry_price_series(repo)
        session.commit()

        assert written == 2
        df = repo.fetch_dataframe(IndustryTimeSeries, sub_industry="Tech Hardware")
        row_2026 = df[df["date"].astype(str) == "2026-06-01"].iloc[0]
        assert row_2026["industry_close_price"] == pytest.approx(150.0 + 220.0)

    def test_tickers_without_a_subindustry_are_excluded(self, session):
        repo = Repository(session)
        session.add(CompanyInfo(ticker="XYZ", name="No Industry Co", sector="Misc.",
                                 industry=None, sub_industry=None))
        session.commit()
        repo.upsert(TickerTimeSeries, [
            {"ticker": "XYZ", "date": date(2026, 6, 1), "close_price": 999.0, "close_price_indexed": 100.0},
        ])
        session.commit()

        written = refresh_industry_price_series(repo)
        session.commit()
        assert written == 0


class TestRefreshIndustryPriceYoy:
    def test_runs_after_industry_price_series(self, session):
        repo = Repository(session)
        _seed_companies(repo, session)
        _seed_prices(repo, session)
        refresh_industry_price_series(repo)
        session.commit()

        written = refresh_industry_price_yoy(repo)
        session.commit()

        assert written == 1
        df = repo.fetch_dataframe(IndustryTimeSeriesYoY)
        expected = (150.0 + 220.0) / (100.0 + 200.0) - 1
        assert df.iloc[0]["industry_close_price_yoy"] == pytest.approx(expected * 100)


class TestRefreshIndustryMetrics:
    def test_averages_across_tickers_in_the_same_subindustry(self, session):
        repo = Repository(session)
        _seed_companies(repo, session)
        _seed_quarterlies(repo, session)

        written = refresh_industry_metrics(repo)
        session.commit()

        assert written == 2
        df = repo.fetch_dataframe(IndustryMetrics, quarter_reporting="2026_1")
        assert df.iloc[0]["basic_eps"] == pytest.approx((1.5 + 2.2) / 2)


class TestRefreshValuationClusters:
    def test_writes_a_row_per_ticker_per_subindustry(self, session):
        repo = Repository(session)
        _seed_companies(repo, session)  # AAPL, MSFT, both Tech Hardware
        _seed_recent_metrics(repo, session, ticker="AAPL")
        _seed_recent_metrics(repo, session, ticker="MSFT", price_eps_ratio=21.0)

        written = refresh_valuation_clusters(repo)
        session.commit()

        assert written == 2
        df = repo.fetch_dataframe(ClusterMembership)
        assert set(df["ticker"]) == {"AAPL", "MSFT"}
        assert (df["date"].astype(str) == str(date.today())).all()

    def test_no_company_info_means_nothing_to_cluster(self, session):
        repo = Repository(session)
        written = refresh_valuation_clusters(repo)
        assert written == 0

    def test_ignore_mode_does_not_overwrite_a_same_day_run(self, session):
        repo = Repository(session)
        _seed_companies(repo, session)
        _seed_recent_metrics(repo, session, ticker="AAPL")
        refresh_valuation_clusters(repo)
        session.commit()

        # A second run today shouldn't duplicate or error on the existing row.
        refresh_valuation_clusters(repo)
        session.commit()

        df = repo.fetch_dataframe(ClusterMembership, ticker="AAPL")
        assert len(df) == 1


class TestRunAll:
    def test_populates_every_aggregate_table_without_error(self, session):
        repo = Repository(session)
        _seed_companies(repo, session)
        _seed_prices(repo, session)
        _seed_quarterlies(repo, session)
        _seed_recent_metrics(repo, session, ticker="AAPL")
        _seed_recent_metrics(repo, session, ticker="MSFT", price_eps_ratio=21.0)

        run_all(repo)
        session.commit()

        assert not repo.fetch_dataframe(ClusterMembership).empty
        assert not repo.fetch_dataframe(TickerTimeSeriesYoY).empty
        assert not repo.fetch_dataframe(QuarterlyFinancialDataYoY).empty
        assert not repo.fetch_dataframe(IndustryTimeSeries).empty
        assert not repo.fetch_dataframe(IndustryTimeSeriesYoY).empty
        assert not repo.fetch_dataframe(IndustryMetrics).empty
        assert not repo.fetch_dataframe(IndustryMetricsYoY).empty
