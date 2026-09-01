"""
Top-level data pipeline.

This is the piece that was previously split across `data/main.py`
(`create_ticker_data`, `create_aggregations_data`) and the root `main.py`
(`main_run`'s recency-check loops and the asset-class refresh loop). It ties
together every other module built so far:

    YFinanceClient (raw fetch) -> transforms/ (pure pandas) -> Repository (persist)

then calls `aggregations.run_all()` to refresh the materialized YoY/industry
tables. It does not touch the dashboard/terminal — same scope boundary as
the rest of this refactor.

Key differences from the original:

- Per-ticker ingestion is a single function (`ingest_ticker`) instead of the
  25-line inline loop body in `create_ticker_data`, and is directly
  unit-testable with a fake client (no network, no database).
- Failure handling is explicit: a `DataRetrievalError` from the client, an
  empty balance sheet/quarterly financials, or a missing sector all skip the
  ticker with a logged reason, rather than the original's mix of a bare
  `except AttributeError`, a `DataRetrievalError` class that was defined but
  never actually raised anywhere, and a couple of silent `pass` branches.
- `CompanyInfo` is always written before any table that has a foreign key on
  it (ticker_time_series, quarterly_financial_data, etc.), and that FK is
  now actually enforced (see database.py) rather than merely declared.
"""
from __future__ import annotations

import logging
from typing import Dict, List

import pandas as pd

from . import aggregations
from .clients.yfinance_client import DataRetrievalError, YFinanceClient
from .config import settings
from .constants import asset_name_to_class, asset_symbol_to_name, asset_symbols
from .models import (
    AssetClassTimeSeries,
    BalanceSheetData,
    CashflowStatementData,
    CompanyInfo,
    QuarterlyFinancialData,
    TickerMostRecentMetric,
    TickerTimeSeries,
)
from .repository import Repository
from .transforms.asset_classes import transform_asset_class_series
from .transforms.ticker_financials import (
    transform_balance_sheet,
    transform_cashflow,
    transform_company_info,
    transform_price_history,
    transform_quarterly_financials,
    transform_recent_metrics,
)

logger = logging.getLogger(__name__)


def load_company_names() -> pd.DataFrame:
    """Ticker -> company name lookup, sourced from the cached S&P 500
    constituent list (columns include 'Symbol' and 'Security'). Replaces
    the repeated `pd.read_csv(os.path.expanduser('~/Documents/Code/...'))`
    calls scattered across the original main.py/data/main.py/retriever.py.
    """
    return pd.read_csv(settings.sp500_ticker_csv)


def ingest_ticker(
    client: YFinanceClient,
    repo: Repository,
    ticker: str,
    sub_industry: str,
    company_names: pd.DataFrame,
) -> bool:
    """Fetch, transform, and persist everything for one ticker.

    Returns True if the ticker had usable data and was written, False if it
    was skipped. A ticker is skipped if the required financial statements
    are unavailable (delisted/invalid symbol) or if `Ticker.info` has no
    sector (the original's proxy for "not a valid equity").
    """
    try:
        balance_sheet_raw = client.fetch_balance_sheet(ticker)
        quarterly_raw = client.fetch_quarterly_financials(ticker)
    except DataRetrievalError as exc:
        logger.warning("Skipping %s: %s", ticker, exc)
        return False

    if balance_sheet_raw.empty or quarterly_raw.empty:
        logger.info("Skipping %s: no balance sheet or quarterly financials available", ticker)
        return False

    try:
        info = client.fetch_info(ticker)
    except DataRetrievalError as exc:
        logger.warning("Skipping %s: could not fetch info: %s", ticker, exc)
        return False

    name_matches = company_names.loc[company_names["Symbol"] == ticker, "Security"]
    company_name = name_matches.iloc[0] if not name_matches.empty else ticker

    company_info = transform_company_info(info, ticker, company_name, sub_industry)
    if company_info is None:
        logger.info("Skipping %s: no sector info available", ticker)
        return False

    recent_metrics = transform_recent_metrics(info, ticker)
    quarterly = transform_quarterly_financials(quarterly_raw, ticker)
    balance_sheet = transform_balance_sheet(balance_sheet_raw, ticker)
    cashflow = _fetch_and_transform(
        lambda: transform_cashflow(client.fetch_cashflow(ticker), ticker),
        empty=transform_cashflow(pd.DataFrame(), ticker),
        ticker=ticker,
        description="cashflow",
    )
    price_history = _fetch_and_transform(
        lambda: transform_price_history(
            client.fetch_price_history(ticker, period=settings.price_history_period), ticker
        ),
        empty=transform_price_history(pd.DataFrame(), ticker),
        ticker=ticker,
        description="price history",
    )

    # CompanyInfo must be written first: every other table below has a
    # foreign key on ticker -> company_info.ticker, and that FK is enforced.
    repo.upsert(CompanyInfo, [company_info], mode="replace")
    repo.upsert(TickerMostRecentMetric, [recent_metrics], mode="replace")
    repo.upsert_dataframe(TickerTimeSeries, price_history, mode="ignore")
    repo.upsert_dataframe(QuarterlyFinancialData, quarterly, mode="ignore")
    repo.upsert_dataframe(BalanceSheetData, balance_sheet, mode="ignore")
    repo.upsert_dataframe(CashflowStatementData, cashflow, mode="ignore")
    return True


def ingest_tickers(
    client: YFinanceClient,
    repo: Repository,
    ticker_subindustry_map: Dict[str, str],
    max_age_days: int | None = None,
    company_names: pd.DataFrame | None = None,
) -> List[str]:
    """Ingest every ticker in `ticker_subindustry_map` that isn't already
    recently fetched. Returns the tickers actually (re)fetched.
    """
    max_age_days = settings.ticker_recency_days if max_age_days is None else max_age_days
    company_names = load_company_names() if company_names is None else company_names

    fetched: List[str] = []
    for ticker, sub_industry in ticker_subindustry_map.items():
        if repo.is_data_recent(ticker, max_age_days=max_age_days):
            logger.debug("Skipping %s: data is recent", ticker)
            continue
        if ingest_ticker(client, repo, ticker, sub_industry, company_names):
            fetched.append(ticker)

    if fetched:
        repo.record_fetch(fetched)
    return fetched


def ingest_asset_classes(
    client: YFinanceClient,
    repo: Repository,
    max_age_days: int | None = None,
) -> List[str]:
    """Fetch/transform/persist the non-stock asset universe (commodities,
    indices, ETFs, FX), skipping symbols already fetched recently. Returns
    the symbols actually (re)fetched.
    """
    max_age_days = settings.asset_recency_days if max_age_days is None else max_age_days

    stale_symbols = [s for s in asset_symbols() if not repo.is_data_recent(s, max_age_days=max_age_days)]
    if not stale_symbols:
        return []

    try:
        raw = client.fetch_multi_asset_history(stale_symbols, period=settings.price_history_period)
    except DataRetrievalError as exc:
        logger.warning("Skipping asset-class refresh: %s", exc)
        return []

    tidy = transform_asset_class_series(raw, asset_symbol_to_name(), asset_name_to_class())
    repo.upsert_dataframe(AssetClassTimeSeries, tidy, mode="ignore")
    repo.record_fetch(stale_symbols)
    return stale_symbols


def run_pipeline(
    repo: Repository,
    ticker_subindustry_map: Dict[str, str],
    client: YFinanceClient | None = None,
) -> None:
    """Full data-layer pipeline: ingest stock tickers, ingest asset classes,
    refresh every materialized aggregate table.

    Replaces the body of the original `main_run()` (excluding the dashboard
    startup, which is out of scope for this refactor) plus
    `create_aggregations_data()`'s YoY/industry portion. Clustering
    (`create_valuation_clusters`) isn't wired in yet — see data/utils.py's
    pending refactor.
    """
    client = client or YFinanceClient()
    fetched_tickers = ingest_tickers(client, repo, ticker_subindustry_map)
    fetched_assets = ingest_asset_classes(client, repo)
    logger.info("Pipeline fetched %d tickers and %d assets", len(fetched_tickers), len(fetched_assets))
    aggregations.run_all(repo)


def _fetch_and_transform(fn, *, empty: pd.DataFrame, ticker: str, description: str) -> pd.DataFrame:
    """Run a fetch+transform step that's allowed to fail without aborting
    the whole ticker (cashflow/price history are supplementary — a missing
    balance sheet or quarterly financials, by contrast, aborts the ticker
    entirely; see ingest_ticker)."""
    try:
        return fn()
    except DataRetrievalError as exc:
        logger.warning("No %s for %s: %s", description, ticker, exc)
        return empty
