"""Shared seeded database for the MCP tool tests.

Universe (all `Widgets` sub-industry unless noted):
  AAA  Alpha Corp     price 100 -> 139 over 40 business days (+1 per day)
  BBB, CCC, DDD       peers; valuation snapshot values chosen so percentiles are easy to check
  EEE  Energy Co      different sector, no sub_industry, no data besides company_info
Asset series: S&P500_ETF (class etf) and US10Y_Yield (class rate), 40 business days each.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from peer_comparison_tool.data.models import (
    AssetClassTimeSeries,
    BalanceSheetData,
    CashflowStatementData,
    ClusterMembership,
    CompanyInfo,
    DataStorageRecord,
    QuarterlyFinancialData,
    QuarterlyFinancialDataYoY,
    TickerMostRecentMetric,
    TickerTimeSeries,
)
from peer_comparison_tool.mcp_server.read_repository import ReadRepository

DAYS = [d.date() for d in pd.bdate_range(end="2026-10-16", periods=40)]
LAST_DAY = DAYS[-1]


@pytest.fixture()
def repo(session) -> ReadRepository:
    r = ReadRepository(session)

    r.upsert(CompanyInfo, [
        {"ticker": "AAA", "name": "Alpha Corp", "sector": "Tech", "industry": "Hardware", "sub_industry": "Widgets"},
        {"ticker": "BBB", "name": "Beta Inc", "sector": "Tech", "industry": "Hardware", "sub_industry": "Widgets"},
        {"ticker": "CCC", "name": "Gamma Ltd", "sector": "Tech", "industry": "Hardware", "sub_industry": "Widgets"},
        {"ticker": "DDD", "name": "Delta plc", "sector": "Tech", "industry": "Hardware", "sub_industry": "Widgets"},
        {"ticker": "EEE", "name": "Energy Co", "sector": "Energy", "industry": None, "sub_industry": None},
    ])

    r.upsert(TickerTimeSeries, [
        {"ticker": "AAA", "date": d, "close_price": 100.0 + i, "close_price_indexed": 100.0 + i}
        for i, d in enumerate(DAYS)
    ])

    r.upsert(AssetClassTimeSeries, [
        {"ticker": "S&P500_ETF", "date": d, "AssetClass": "etf", "close_price": 500.0 + i,
         "close_price_indexed": None, "close_price_yoy": None}
        for i, d in enumerate(DAYS)
    ] + [
        {"ticker": "US10Y_Yield", "date": d, "AssetClass": "rate", "close_price": 4.0 + 0.01 * i,
         "close_price_indexed": None, "close_price_yoy": None}
        for i, d in enumerate(DAYS)
    ])

    quarters = [(date(2025, 12, 31), "2025Q4"), (date(2026, 3, 31), "2026Q1"), (date(2026, 6, 30), "2026Q2")]
    r.upsert(QuarterlyFinancialData, [
        {"ticker": "AAA", "date": d, "quarter_reporting": q, "basic_eps": 1.0 + i, "operating_income": 1e9,
         "operating_income_mm": 1000.0, "net_income": 8e8, "net_income_mm": 800.0, "gross_margin": 40.0 + i,
         "operating_margin": 20.0, "net_margin": float("nan"), "ebitda_margin": 25.0}
        for i, (d, q) in enumerate(quarters)
    ])
    r.upsert(QuarterlyFinancialDataYoY, [
        {"ticker": "AAA", "date": quarters[2][0], "quarter_reporting": "2026Q2", "basic_eps_yoy": 0.5,
         "operating_income_yoy": 0.1, "net_income_yoy": 0.2, "gross_margin_yoy": 1.5,
         "operating_margin_yoy": 0.0, "net_margin_yoy": 0.0, "ebitda_margin_yoy": 0.0},
    ])
    r.upsert(BalanceSheetData, [
        {"ticker": "AAA", "date": date(2024, 12, 31), "annual_reporting": "2025", "ordinary_shares_number": 100,
         "stockholders_equity": 500, "total_liabilities_net_minority_interest": 250.0, "current_assets": 400.0,
         "quick_ratio": 1.6, "equity_ratio": 1.5, "debt_to_equity_ratio": 0.5},
        {"ticker": "AAA", "date": date(2025, 12, 31), "annual_reporting": "2026", "ordinary_shares_number": 100,
         "stockholders_equity": 600, "total_liabilities_net_minority_interest": 300.0, "current_assets": 450.0,
         "quick_ratio": 1.5, "equity_ratio": 1.5, "debt_to_equity_ratio": 0.5},
    ])
    r.upsert(CashflowStatementData, [
        {"ticker": "AAA", "date": date(2025, 12, 31), "free_cash_flow": 5e8, "operating_cash_flow": 7e8,
         "capital_expenditure": -2e8},
    ])

    # price_eps_ratio: AAA 25 vs peers 20/30/40.
    # price_to_book: AAA 2 vs BBB 3, CCC 4, DDD None -> only 2 peers with a value -> no percentile.
    r.upsert(TickerMostRecentMetric, [
        {"ticker": "AAA", "market_cap": 1e11, "price_eps_ratio": 25.0, "price_to_book": 2.0,
         "return_on_equity": 0.2, "debt_to_equity_ratio": 80.0, "profit_margin": 0.15,
         "enterprise_to_ebitda": 12.0, "latest_eps": 4.0, "enterprise_value": 1.1e11},
        {"ticker": "BBB", "market_cap": 3e11, "price_eps_ratio": 20.0, "price_to_book": 3.0,
         "return_on_equity": 0.1, "debt_to_equity_ratio": 60.0, "profit_margin": 0.10,
         "enterprise_to_ebitda": 10.0, "latest_eps": 3.0, "enterprise_value": 3.1e11},
        {"ticker": "CCC", "market_cap": 2e11, "price_eps_ratio": 30.0, "price_to_book": 4.0,
         "return_on_equity": 0.3, "debt_to_equity_ratio": 90.0, "profit_margin": 0.20,
         "enterprise_to_ebitda": 14.0, "latest_eps": 5.0, "enterprise_value": 2.1e11},
        {"ticker": "DDD", "market_cap": 5e10, "price_eps_ratio": 40.0, "price_to_book": None,
         "return_on_equity": 0.4, "debt_to_equity_ratio": 100.0, "profit_margin": 0.25,
         "enterprise_to_ebitda": 16.0, "latest_eps": 6.0, "enterprise_value": 5.1e10},
    ])

    # AAA was a cluster member on the older run and is not on the newer one: "latest" must win.
    r.upsert(ClusterMembership, [
        {"ticker": "AAA", "date": date(2026, 9, 1), "cluster_membership": "Cluster member"},
        {"ticker": "AAA", "date": date(2026, 10, 1), "cluster_membership": "Not cluster member"},
        {"ticker": "BBB", "date": date(2026, 10, 1), "cluster_membership": "Cluster member"},
        {"ticker": "CCC", "date": date(2026, 10, 1), "cluster_membership": "Cluster member"},
    ])

    r.upsert(DataStorageRecord, [{"ticker": "AAA", "version_date": date(2026, 10, 15)}])
    session.flush()
    return r
