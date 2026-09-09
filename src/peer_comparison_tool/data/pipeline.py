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
from .clients.fred_client import FredClient
from .clients.yfinance_client import DataRetrievalError, YFinanceClient
from .config import settings
from .constants import asset_name_to_class, asset_symbol_to_name, asset_symbols
from .models import (
    AssetClassTimeSeries,
    BalanceSheetData,
    CashflowStatementData,
    CompanyInfo,
    EconomicReleaseData,
    QuarterlyFinancialData,
    TickerMostRecentMetric,
    TickerTimeSeries,
)
from .repository import Repository
from .transforms.asset_classes import transform_asset_class_series
from .transforms.economic_releases import FRED_SERIES
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


def _extract_single_ticker_history(batch: pd.DataFrame | None, ticker: str) -> pd.DataFrame:
    """Slice one ticker's OHLCV columns out of a (field, ticker) multi-symbol
    batch frame (as returned by `fetch_multi_symbol_history`), and flatten
    back to the single-level-column shape `transform_price_history()`
    expects — the same shape a lone `Ticker(ticker).history()` call would
    have returned. Returns an empty frame if the batch doesn't have this
    ticker at all (e.g. its chunk failed and was skipped) or if `batch`
    itself is `None` (the whole batched fetch failed)."""
    if batch is None or ticker not in batch.columns.get_level_values(1):
        return pd.DataFrame()
    return batch.xs(ticker, level=1, axis=1).dropna(how="all")


def ingest_ticker(
        client: YFinanceClient,
        repo: Repository,
        ticker: str,
        sub_industry: str,
        company_names: pd.DataFrame,
        price_history_raw: pd.DataFrame | None = None,
) -> bool:
    """Fetch, transform, and persist everything for one ticker.

    `price_history_raw` lets a caller pass in price data already fetched as
    part of a batched multi-ticker call (see `ingest_tickers`) instead of
    this function fetching it itself one ticker at a time — pass `None`
    (the default) to fall back to the original per-ticker
    `client.fetch_price_history(ticker)` call, e.g. for standalone/test use.

    Returns True if the ticker had usable data and was written, False if it
    was skipped. A ticker is skipped if the required financial statements
    are unavailable (delisted/invalid symbol) or if `Ticker.info` has no
    sector (the original's proxy for \"not a valid equity\").
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
    if price_history_raw is not None:
        # Already fetched as part of a batched multi-ticker call -- just
        # transform it, no network call (and nothing to retry) here.
        price_history = transform_price_history(price_history_raw, ticker)
    else:
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

    stale_tickers = [
        ticker for ticker in ticker_subindustry_map
        if not repo.is_data_recent(ticker, max_age_days=max_age_days)
    ]
    if not stale_tickers:
        return []

    # Batch-fetch price history for every stale ticker in one (chunked)
    # pass, rather than a separate Ticker(t).history() call per ticker
    # inside the loop below -- looping one ticker at a time is exactly the
    # pattern that triggers Yahoo's rate limiter almost immediately.
    # Balance sheet/quarterly financials/cashflow/info have no equivalent
    # yfinance batch endpoint, so those stay per-ticker inside ingest_ticker.
    #
    # If the batch call fails entirely (every chunk exhausted its retries),
    # this run proceeds with no price history for any stale ticker rather
    # than falling back to a per-ticker fetch loop -- that fallback would
    # just recreate the exact one-call-per-ticker pattern this batching
    # exists to avoid, right after Yahoo has already shown signs of
    # rate-limiting. Price history is supplementary (see
    # _fetch_and_transform's docstring), so this doesn't lose the ticker
    # entirely; a later pipeline run will pick prices up once the pipeline
    # decides this ticker's data is stale enough to refetch.
    try:
        price_history_batch = client.fetch_multi_symbol_history(
            stale_tickers,
            period=settings.price_history_period,
            chunk_size=settings.asset_fetch_chunk_size,
            chunk_delay_seconds=settings.asset_fetch_chunk_delay_seconds,
        )
    except DataRetrievalError as exc:
        logger.warning(
            "Batched price history fetch failed entirely for all %d stale ticker(s); "
            "proceeding without price history this run rather than retrying per-ticker: %s",
            len(stale_tickers), exc,
        )
        price_history_batch = None

    fetched: List[str] = []
    for ticker in stale_tickers:
        sub_industry = ticker_subindustry_map[ticker]
        price_history_raw = _extract_single_ticker_history(price_history_batch, ticker)
        if ingest_ticker(client, repo, ticker, sub_industry, company_names, price_history_raw=price_history_raw):
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
        raw = client.fetch_multi_symbol_history(
            stale_symbols,
            period=settings.price_history_period,
            chunk_size=settings.asset_fetch_chunk_size,
            chunk_delay_seconds=settings.asset_fetch_chunk_delay_seconds,
        )
    except DataRetrievalError as exc:
        logger.warning("Skipping asset-class refresh: %s", exc)
        return []

    tidy = transform_asset_class_series(raw, asset_symbol_to_name(), asset_name_to_class())
    repo.upsert_dataframe(AssetClassTimeSeries, tidy, mode="ignore")
    repo.record_fetch(stale_symbols)
    return stale_symbols


def ingest_economic_releases(
        client: FredClient,
        repo: Repository,
        series_ids: List[str] | None = None,
        max_age_days: int | None = None,
) -> List[str]:
    """Fetch/persist the latest observations for every FRED series in
    `series_ids` (defaults to `FRED_SERIES`, the starter list -- CPI,
    JOLTS, payrolls, unemployment, Fed funds), skipping series already
    fetched recently. Returns the series actually (re)fetched.

    No transform step of its own (unlike `ingest_asset_classes`): FRED
    already returns clean `(date, value)` observations, there's no
    equivalent of yfinance's messy multi-symbol column shape to tidy up
    here. `economic_releases.build_release_summary` does the
    latest-vs-prior comparison work, on the dashboard side, from whatever
    this has persisted.
    """
    max_age_days = settings.fred_recency_days if max_age_days is None else max_age_days
    series_ids = list(FRED_SERIES.keys()) if series_ids is None else series_ids

    stale_series = [s for s in series_ids if not repo.is_data_recent(s, max_age_days=max_age_days)]
    if not stale_series:
        return []

    fetched = []
    for series_id in stale_series:
        try:
            observations = client.fetch_series_observations(series_id)
        except DataRetrievalError as exc:
            logger.warning("Skipping FRED series %s: %s", series_id, exc)
            continue
        if observations.empty:
            continue

        tidy = observations.copy()
        tidy["series_id"] = series_id
        repo.upsert_dataframe(EconomicReleaseData, tidy, mode="ignore")
        fetched.append(series_id)

    repo.record_fetch(fetched)
    return fetched


def run_pipeline(
        repo: Repository,
        ticker_subindustry_map: Dict[str, str],
        client: YFinanceClient | None = None,
        fred_client: FredClient | None = None,
) -> None:
    """Full data-layer pipeline: ingest stock tickers, ingest asset classes,
    optionally ingest economic release data, refresh every materialized
    aggregate table (including valuation clusters).

    Replaces the body of the original `main_run()` (excluding the dashboard
    startup, which is out of scope for this refactor) plus
    `create_aggregations_data()`.

    `fred_client` is optional and skipped entirely (with a log line, not an
    error) if not supplied and `settings.fred_api_key` isn't set -- FRED
    requires signing up for a free API key, and nothing else in the
    pipeline should be blocked on that being configured. Pass a
    `FredClient` explicitly (or set `FRED_API_KEY`) to enable it.
    """
    client = client or YFinanceClient()
    fetched_tickers = ingest_tickers(client, repo, ticker_subindustry_map)
    fetched_assets = ingest_asset_classes(client, repo)
    logger.info("Pipeline fetched %d tickers and %d assets", len(fetched_tickers), len(fetched_assets))

    if fred_client is None and settings.fred_api_key:
        fred_client = FredClient(api_key=settings.fred_api_key)
    if fred_client is not None:
        fetched_releases = ingest_economic_releases(fred_client, repo)
        logger.info("Pipeline fetched %d economic release series", len(fetched_releases))
    else:
        logger.info("Skipping economic release ingestion: no FRED API key configured")

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