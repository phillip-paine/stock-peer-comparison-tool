"""
Aggregation pipeline.

Runs once per data-pipeline invocation (same as the original), fetching raw
per-ticker data already written by ingestion, deriving industry-level and
YoY series with the pure functions in `transforms/time_series.py`, and
writing the results back as materialized tables. The dashboard never calls
into this module directly — it only ever reads the tables this writes.

Replaces `db_utils.update_ticker_yoy_aggregations()` and
`db_utils.update_industry_aggregations()`, and the SQL in `data/queries.py`
that backed them.
"""
from __future__ import annotations

import logging

from .models import (
    CompanyInfo,
    IndustryMetrics,
    IndustryMetricsYoY,
    IndustryTimeSeries,
    IndustryTimeSeriesYoY,
    QuarterlyFinancialData,
    QuarterlyFinancialDataYoY,
    TickerTimeSeries,
    TickerTimeSeriesYoY,
)
from .repository import Repository
from .transforms.time_series import (
    aggregate_mean_by_quarter,
    aggregate_sum,
    compute_yoy_by_date,
    compute_yoy_by_quarter,
)

logger = logging.getLogger(__name__)

TICKER_PRICE_COLS = ["close_price", "close_price_indexed"]
QUARTERLY_METRIC_COLS = [
    "basic_eps", "operating_income", "net_income",
    "gross_margin", "operating_margin", "net_margin", "ebitda_margin",
]


def refresh_ticker_price_yoy(repo: Repository) -> int:
    """Materialize ticker_ts_yoy from ticker_time_series."""
    ticker_ts = repo.fetch_dataframe(TickerTimeSeries)
    yoy = compute_yoy_by_date(
        ticker_ts, group_cols=["ticker"], date_col="date",
        value_cols=TICKER_PRICE_COLS, suffix="_yoy",
    )
    written = repo.upsert_dataframe(TickerTimeSeriesYoY, yoy, mode="replace")
    logger.info("Refreshed ticker_ts_yoy: %d rows", written)
    return written


def refresh_ticker_metric_yoy(repo: Repository) -> int:
    """Materialize ticker_metrics_yoy from quarterly_financial_data."""
    quarterly = repo.fetch_dataframe(QuarterlyFinancialData)
    yoy = compute_yoy_by_quarter(
        quarterly, group_cols=["ticker"], quarter_col="quarter_reporting",
        date_col="date", value_cols=QUARTERLY_METRIC_COLS, suffix="_yoy",
    )
    written = repo.upsert_dataframe(QuarterlyFinancialDataYoY, yoy, mode="replace")
    logger.info("Refreshed ticker_metrics_yoy: %d rows", written)
    return written


def refresh_industry_price_series(repo: Repository) -> int:
    """Materialize industry_time_series by summing ticker-level prices
    within each sub-industry, per date."""
    ticker_ts = repo.fetch_dataframe(TickerTimeSeries)
    company_info = repo.fetch_dataframe(CompanyInfo)
    if ticker_ts.empty or company_info.empty:
        return 0

    merged = ticker_ts.merge(company_info[["ticker", "sub_industry"]], on="ticker", how="inner")
    merged = merged.dropna(subset=["sub_industry"])
    industry_prices = aggregate_sum(
        merged, group_cols=["sub_industry", "date"], value_cols=TICKER_PRICE_COLS,
    )
    industry_prices = industry_prices.rename(columns={
        "close_price": "industry_close_price",
        "close_price_indexed": "industry_close_price_indexed",
    })
    written = repo.upsert_dataframe(IndustryTimeSeries, industry_prices, mode="replace")
    logger.info("Refreshed industry_time_series: %d rows", written)
    return written


def refresh_industry_price_yoy(repo: Repository) -> int:
    """Materialize industry_time_series_yoy from industry_time_series.
    Must run after refresh_industry_price_series()."""
    industry_ts = repo.fetch_dataframe(IndustryTimeSeries)
    yoy = compute_yoy_by_date(
        industry_ts, group_cols=["sub_industry"], date_col="date",
        value_cols=["industry_close_price", "industry_close_price_indexed"], suffix="_yoy",
    )
    written = repo.upsert_dataframe(IndustryTimeSeriesYoY, yoy, mode="replace")
    logger.info("Refreshed industry_time_series_yoy: %d rows", written)
    return written


def refresh_industry_metrics(repo: Repository) -> int:
    """Materialize industry_metrics by averaging ticker-level quarterly
    financials within each sub-industry, per reporting quarter."""
    quarterly = repo.fetch_dataframe(QuarterlyFinancialData)
    company_info = repo.fetch_dataframe(CompanyInfo)
    if quarterly.empty or company_info.empty:
        return 0

    merged = quarterly.merge(company_info[["ticker", "sub_industry"]], on="ticker", how="inner")
    merged = merged.dropna(subset=["sub_industry"])
    industry_metrics = aggregate_mean_by_quarter(
        merged, group_cols=["sub_industry"], quarter_col="quarter_reporting",
        date_col="date", value_cols=QUARTERLY_METRIC_COLS,
    )
    written = repo.upsert_dataframe(IndustryMetrics, industry_metrics, mode="replace")
    logger.info("Refreshed industry_metrics: %d rows", written)
    return written


def refresh_industry_metrics_yoy(repo: Repository) -> int:
    """Materialize industry_metrics_yoy from industry_metrics.
    Must run after refresh_industry_metrics()."""
    industry_metrics = repo.fetch_dataframe(IndustryMetrics)
    yoy = compute_yoy_by_quarter(
        industry_metrics, group_cols=["sub_industry"], quarter_col="quarter_reporting",
        date_col="date", value_cols=QUARTERLY_METRIC_COLS, suffix="_yoy",
    )
    written = repo.upsert_dataframe(IndustryMetricsYoY, yoy, mode="replace")
    logger.info("Refreshed industry_metrics_yoy: %d rows", written)
    return written


def run_all(repo: Repository) -> None:
    """Refresh every materialized aggregate table, in dependency order.
    This is the direct replacement for the aggregation portion of
    `data/main.py`'s `create_aggregations_data()` (clustering is handled
    separately — see data/clustering.py once that module exists)."""
    refresh_ticker_price_yoy(repo)
    refresh_ticker_metric_yoy(repo)
    refresh_industry_price_series(repo)
    refresh_industry_price_yoy(repo)
    refresh_industry_metrics(repo)
    refresh_industry_metrics_yoy(repo)
