"""Tests for comparison_tool.data_loader, which replaced the ~40-line
inline data-loading block that used to live in comparison_tool.app.create_app().
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.peer_comparison_tool.comparison_tool.data_loader import load_dashboard_data
from src.peer_comparison_tool.data.models import (
    AssetClassTimeSeries,
    BalanceSheetData,
    ClusterMembership,
    CompanyInfo,
    IndustryMetricsYoY,
    IndustryTimeSeries,
    IndustryTimeSeriesYoY,
    QuarterlyFinancialData,
    QuarterlyFinancialDataYoY,
    TickerMostRecentMetric,
    TickerTimeSeries,
    TickerTimeSeriesYoY,
)
from src.peer_comparison_tool.data.repository import Repository


def _seed_company_info(repo: Repository) -> None:
    repo.upsert(
        CompanyInfo,
        [
            {"ticker": "AAA", "name": "Aaa Corp", "sector": "Tech", "industry": "Software", "sub_industry": "Apps"},
            {"ticker": "BBB", "name": "Bbb Corp", "sector": "Tech", "industry": "Software", "sub_industry": "Apps"},
        ],
    )


def test_load_dashboard_data_applies_column_renames_and_snapshot_join(session):
    repo = Repository(session)
    _seed_company_info(repo)
    repo.upsert(
        TickerMostRecentMetric,
        [
            {"ticker": "AAA", "market_cap": 2_000_000, "price_eps_ratio": 20.0, "price_to_book": 3.0,
             "return_on_equity": 0.15, "debt_to_equity_ratio": 0.5, "profit_margin": 0.2,
             "enterprise_to_ebitda": 12.0, "latest_eps": 5.0, "enterprise_value": 2_100_000},
            {"ticker": "BBB", "market_cap": 500_000, "price_eps_ratio": 15.0, "price_to_book": 2.0,
             "return_on_equity": 0.10, "debt_to_equity_ratio": 0.3, "profit_margin": 0.1,
             "enterprise_to_ebitda": 8.0, "latest_eps": 2.0, "enterprise_value": 550_000},
        ],
    )
    # Only AAA has a cluster-membership row -- BBB should be dropped by the
    # (preserved, original-behaviour) inner join.
    repo.upsert(ClusterMembership, [{"ticker": "AAA", "date": date(2024, 3, 1), "cluster_membership": "Cluster member"}])
    repo.upsert(QuarterlyFinancialData, [])
    repo.upsert(BalanceSheetData, [])
    session.commit()

    data = load_dashboard_data(repo)

    assert list(data.snapshot_recent_metrics["ticker"]) == ["AAA"]
    assert "label" in data.snapshot_recent_metrics.columns
    assert data.snapshot_recent_metrics.loc[0, "label"] == "Cluster member"
    assert "enterpriseToEbitda" in data.snapshot_recent_metrics.columns
    assert data.snapshot_recent_metrics.loc[0, "market_cap_MM"] == pytest.approx(2.0)
    assert data.latest_enterprise_value.loc["AAA", "enterprise_value"] == 2_100_000


def test_load_dashboard_data_renames_quarterly_and_balance_sheet_columns(session):
    repo = Repository(session)
    _seed_company_info(repo)
    repo.upsert(TickerMostRecentMetric, [])
    repo.upsert(ClusterMembership, [])
    repo.upsert(
        QuarterlyFinancialData,
        [{
            "ticker": "AAA", "date": date(2024, 3, 31), "quarter_reporting": "Q1-2024",
            "basic_eps": 1.5, "operating_income": 100.0, "operating_income_mm": 0.1,
            "net_income": 80.0, "net_income_mm": 0.08, "gross_margin": 0.6,
            "operating_margin": 0.3, "net_margin": 0.25, "ebitda_margin": 0.35,
        }],
    )
    repo.upsert(
        BalanceSheetData,
        [{
            "ticker": "AAA", "date": date(2024, 3, 31), "annual_reporting": "FY2024",
            "ordinary_shares_number": 1000, "stockholders_equity": 500,
            "total_liabilities_net_minority_interest": 200.0, "current_assets": 300.0,
            "quick_ratio": 1.2, "equity_ratio": 0.6, "debt_to_equity_ratio": 0.4,
        }],
    )
    session.commit()

    data = load_dashboard_data(repo)

    for col in ["Gross Margin", "Operating Margin", "Net Margin", "EBITDA Margin", "Basic EPS"]:
        assert col in data.qfin_data.columns
    for col in ["Quick Ratio", "Equity Ratio", "Debt-to-Equity Ratio"]:
        assert col in data.bs_data.columns


def test_price_over_eps_uses_ffilled_close_price(session):
    repo = Repository(session)
    _seed_company_info(repo)
    repo.upsert(TickerMostRecentMetric, [])
    repo.upsert(ClusterMembership, [])
    repo.upsert(
        TickerTimeSeries,
        [
            {"ticker": "AAA", "date": date(2024, 1, 1), "close_price": 100.0, "close_price_indexed": 100.0},
        ],
    )
    repo.upsert(TickerTimeSeriesYoY, [])
    repo.upsert(
        QuarterlyFinancialData,
        [{
            "ticker": "AAA", "date": date(2024, 3, 31), "quarter_reporting": "Q1-2024",
            "basic_eps": 2.0, "operating_income": 0.0, "operating_income_mm": 0.0,
            "net_income": 0.0, "net_income_mm": 0.0, "gross_margin": 0.5,
            "operating_margin": 0.2, "net_margin": 0.1, "ebitda_margin": 0.15,
        }],
    )
    repo.upsert(BalanceSheetData, [])
    session.commit()

    data = load_dashboard_data(repo)

    row = data.qfin_data.loc[data.qfin_data["ticker"] == "AAA"].iloc[0]
    # close_price forward-filled from the only price row (Jan 1) onto the
    # Mar 31 quarterly-report row -> 100.0 / 2.0 EPS = 50.0
    assert row["close_price"] == pytest.approx(100.0)
    assert row["Price Over EPS"] == pytest.approx(50.0)


def test_quarterly_price_ffill_does_not_leak_across_tickers(session):
    """Regression test for the bug found while tracing the original
    create_app(): forward-filling close_price across the whole multi-ticker
    frame (instead of grouping by ticker first) could let one ticker's
    quarterly row pick up the *previous ticker's* last known price."""
    repo = Repository(session)
    _seed_company_info(repo)
    repo.upsert(TickerMostRecentMetric, [])
    repo.upsert(ClusterMembership, [])
    repo.upsert(
        TickerTimeSeries,
        [
            # AAA has a price on Jan 1 only.
            {"ticker": "AAA", "date": date(2024, 1, 1), "close_price": 999.0, "close_price_indexed": 100.0},
            # BBB has no price data at all before its quarterly report date.
        ],
    )
    repo.upsert(TickerTimeSeriesYoY, [])
    repo.upsert(
        QuarterlyFinancialData,
        [{
            # BBB's report date sorts after AAA's only price row.
            "ticker": "BBB", "date": date(2024, 2, 1), "quarter_reporting": "Q1-2024",
            "basic_eps": 1.0, "operating_income": 0.0, "operating_income_mm": 0.0,
            "net_income": 0.0, "net_income_mm": 0.0, "gross_margin": 0.5,
            "operating_margin": 0.2, "net_margin": 0.1, "ebitda_margin": 0.15,
        }],
    )
    repo.upsert(BalanceSheetData, [])
    session.commit()

    data = load_dashboard_data(repo)

    bbb_row = data.qfin_data.loc[data.qfin_data["ticker"] == "BBB"].iloc[0]
    # BBB must NOT have inherited AAA's 999.0 price -- it should be NaN,
    # since BBB has no price history of its own to forward-fill from.
    assert pd.isna(bbb_row["close_price"])


def test_industry_series_rebased_to_100_at_first_date(session):
    repo = Repository(session)
    repo.upsert(
        IndustryTimeSeries,
        [
            {"sub_industry": "Apps", "date": date(2024, 1, 1), "industry_close_price": 1000.0, "industry_close_price_indexed": 50.0},
            {"sub_industry": "Apps", "date": date(2024, 2, 1), "industry_close_price": 1100.0, "industry_close_price_indexed": 55.0},
        ],
    )
    repo.upsert(IndustryTimeSeriesYoY, [])
    repo.upsert(IndustryMetricsYoY, [])
    session.commit()

    data = load_dashboard_data(repo)

    series = data.industry_series_data.sort_values("date").reset_index(drop=True)
    assert series.loc[0, "industry_close_price_indexed"] == pytest.approx(100.0)
    assert series.loc[1, "industry_close_price_indexed"] == pytest.approx(110.0)


def test_yoy_metric_renames_applied_to_ticker_and_industry_frames(session):
    repo = Repository(session)
    _seed_company_info(repo)
    repo.upsert(TickerMostRecentMetric, [])
    repo.upsert(ClusterMembership, [])
    repo.upsert(
        QuarterlyFinancialDataYoY,
        [{
            "ticker": "AAA", "date": date(2024, 3, 31), "quarter_reporting": "Q1-2024",
            "basic_eps_yoy": 5.0, "operating_income_yoy": 3.0, "net_income_yoy": 4.0,
            "gross_margin_yoy": 1.0, "operating_margin_yoy": 2.0, "net_margin_yoy": 1.5,
            "ebitda_margin_yoy": 2.5,
        }],
    )
    repo.upsert(
        IndustryMetricsYoY,
        [{
            "sub_industry": "Apps", "date": date(2024, 3, 31), "quarter_reporting": "Q1-2024",
            "basic_eps_yoy": 5.0, "operating_income_yoy": 3.0, "net_income_yoy": 4.0,
            "gross_margin_yoy": 1.0, "operating_margin_yoy": 2.0, "net_margin_yoy": 1.5,
            "ebitda_margin_yoy": 2.5,
        }],
    )
    session.commit()

    data = load_dashboard_data(repo)

    expected_cols = {"Basic EPS YoY", "Net Income YoY", "Operating Income YoY", "Gross Margin YoY", "Net Margin YoY"}
    assert expected_cols.issubset(data.ticker_metric_yoy_data.columns)
    assert expected_cols.issubset(data.industry_metrics_yoy_data.columns)
