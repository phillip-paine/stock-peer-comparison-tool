"""
Loads every DataFrame the dashboard needs, once, at app startup.

Replaces the ~40-line block that used to live directly inside
`comparison_tool.app.create_app()` and called the retired
`fetch_table_data()` / `get_table_data_query()` helpers from the old
`data_old` package (deleted as part of the data-layer cutover, but still
imported by `app.py` — see the bugs section of the refactor handoff notes).
This module is now the *only* place in the dashboard that talks to the data
layer; every page/layout/callback module downstream is unchanged and still
just receives plain DataFrames.

Traced from the original `create_app()` before rewriting (not guessed),
preserving two behaviours exactly:

1. The non-obvious merges: `cluster_table` onto `ticker_most_recent_metric_data`,
   forward-filled `close_price` onto quarterly financials to compute P/E,
   and the industry price index re-based to 100 at its first date.
2. The dashboard pages still reference the *old* display-style column names
   ('Basic EPS', 'Quick Ratio', 'Net Margin YoY', 'enterpriseToEbitda', ...)
   as literal strings — confirmed by grepping every file under
   `comparison_tool/`, not assumed. Rather than rewrite every page file
   (a bigger, separate change — see handoff notes section 10), columns are
   renamed once here at the load boundary, via the *_RENAMES maps below.

One real bug found and fixed while tracing this block (see docstring on
`_load_quarterly_financials` for detail): the price-forward-fill used to
run across the whole multi-ticker frame without grouping by ticker first,
so a ticker with no quarterly-financials row on a given date could pick up
the *previous ticker's* last price rather than its own.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.peer_comparison_tool.data.models import (
    AssetClassTimeSeries,
    BalanceSheetData,
    CashflowStatementData,
    CompanyInfo,
    EconomicReleaseData,
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

# Quarterly-financials metric columns -> the display-style names
# company_quarterly_report_page.py references as literal strings.
QUARTERLY_METRIC_RENAMES = {
    "basic_eps": "Basic EPS",
    "gross_margin": "Gross Margin",
    "operating_margin": "Operating Margin",
    "net_margin": "Net Margin",
    "ebitda_margin": "EBITDA Margin",
}

# YoY columns -> display-style names, shared by ticker_metrics_yoy and
# industry_metrics_yoy (individual_company_overview_page.py reads both
# frames with the same literal column names).
YOY_METRIC_RENAMES = {
    "basic_eps_yoy": "Basic EPS YoY",
    "net_income_yoy": "Net Income YoY",
    "operating_income_yoy": "Operating Income YoY",
    "gross_margin_yoy": "Gross Margin YoY",
    "net_margin_yoy": "Net Margin YoY",
}

# Balance-sheet columns -> display-style names company_balance_sheet_report_page.py
# references as literal strings.
BALANCE_SHEET_RENAMES = {
    "quick_ratio": "Quick Ratio",
    "equity_ratio": "Equity Ratio",
    "debt_to_equity_ratio": "Debt-to-Equity Ratio",
}

# comparison_page.py references this one column in its original mixed-case
# form (it was never snake_case even in the pre-refactor schema).
SNAPSHOT_METRIC_RENAMES = {
    "enterprise_to_ebitda": "enterpriseToEbitda",
}

# discounted_cashflow_model_page.py references this as a literal string.
CASHFLOW_RENAMES = {
    "free_cash_flow": "Free Cash Flow",
}


@dataclass
class DashboardData:
    """Every DataFrame a page/layout/callback module needs, loaded once at
    app startup. One field per argument the old `create_app()` used to pass
    around loosely as local variables."""

    company_info: pd.DataFrame
    economic_data: pd.DataFrame
    snapshot_recent_metrics: pd.DataFrame
    latest_enterprise_value: pd.DataFrame
    ticker_series_data: pd.DataFrame
    ticker_metric_yoy_data: pd.DataFrame
    industry_series_data: pd.DataFrame
    industry_metrics_yoy_data: pd.DataFrame
    qfin_data: pd.DataFrame
    bs_data: pd.DataFrame
    cashflow_map: dict[str, pd.DataFrame]
    economic_release_data: pd.DataFrame


def load_dashboard_data(repo: Repository) -> DashboardData:
    """Fetch and shape every table the dashboard's pages read, via `repo`.

    Call this once inside a `session_scope()` block at app startup (see
    `app.create_app()`) — same "load everything once, read cheaply many
    times" approach `create_app()` already used, just going through the
    Repository instead of raw SQL.
    """
    company_info = repo.fetch_dataframe(CompanyInfo)

    economic_data = repo.fetch_dataframe(AssetClassTimeSeries)

    snapshot_recent_metrics, latest_enterprise_value = _load_snapshot_recent_metrics(
        repo, company_info
    )

    ticker_series_data, ticker_metric_yoy_data = _load_ticker_series(repo, company_info)

    industry_series_data, industry_metrics_yoy_data = _load_industry_series(repo)

    qfin_data = _load_quarterly_financials(repo, company_info, ticker_series_data)

    bs_data = _load_balance_sheet(repo, company_info)

    cashflow_map = _load_cashflow_map(repo)

    # Empty (rather than absent) if no FRED_API_KEY was set at pipeline
    # time and this table was never populated -- see pipeline.py's
    # ingest_economic_releases; the page handles an empty frame gracefully.
    economic_release_data = repo.fetch_dataframe(EconomicReleaseData)

    return DashboardData(
        company_info=company_info,
        economic_data=economic_data,
        snapshot_recent_metrics=snapshot_recent_metrics,
        latest_enterprise_value=latest_enterprise_value,
        ticker_series_data=ticker_series_data,
        ticker_metric_yoy_data=ticker_metric_yoy_data,
        industry_series_data=industry_series_data,
        industry_metrics_yoy_data=industry_metrics_yoy_data,
        qfin_data=qfin_data,
        bs_data=bs_data,
        cashflow_map=cashflow_map,
        economic_release_data=economic_release_data,
    )


def _load_snapshot_recent_metrics(
    repo: Repository, company_info: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Latest valuation snapshot per ticker, joined with company info and
    the latest DBSCAN cluster label. Feeds the comparison page.

    Note: the join against cluster membership is an *inner* join, exactly
    as in the original — a ticker with no cluster-membership row is dropped
    from the snapshot entirely, not just left with a blank label. Preserved
    as-is rather than "fixed" to a left join, since that's a call about
    intended behaviour (only show tickers DBSCAN has actually classified)
    that's Phillip's to make, not an obvious bug. One consequence worth
    flagging: `data/clustering.py` (the module that populates `cluster_table`)
    hasn't been built yet, so until it exists `cluster_table` is empty and
    this join will currently drop every ticker — same as it would have with
    the original code today.
    """
    snapshot = repo.fetch_dataframe(TickerMostRecentMetric)
    snapshot = snapshot.merge(company_info, on="ticker", how="left")
    snapshot["market_cap_MM"] = snapshot["market_cap"].clip(lower=1) / 1_000_000

    cluster = repo.latest_cluster_membership()
    cluster = cluster.rename(columns={"cluster_membership": "label"})
    snapshot = snapshot.merge(cluster[["ticker", "label"]], on="ticker", how="inner")

    snapshot = snapshot.rename(columns=SNAPSHOT_METRIC_RENAMES)

    latest_enterprise_value = snapshot[["ticker", "enterprise_value"]].set_index("ticker")
    return snapshot, latest_enterprise_value


def _load_ticker_series(
    repo: Repository, company_info: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-ticker daily price series (with YoY merged in) and per-ticker
    quarterly-metric YoY series, both joined with company info and sorted
    for charting."""
    ticker_series = repo.fetch_dataframe(TickerTimeSeries)
    ticker_series = ticker_series.merge(company_info, on="ticker", how="left")

    ticker_series_yoy = repo.fetch_dataframe(TickerTimeSeriesYoY)
    ticker_series = ticker_series.merge(
        ticker_series_yoy, on=["ticker", "date"], how="left"
    )
    ticker_series = ticker_series.sort_values(by=["ticker", "date"])

    ticker_metric_yoy = repo.fetch_dataframe(QuarterlyFinancialDataYoY)
    ticker_metric_yoy = ticker_metric_yoy.merge(company_info, on="ticker", how="left")
    ticker_metric_yoy = ticker_metric_yoy.sort_values(by=["ticker", "date"])
    ticker_metric_yoy = ticker_metric_yoy.rename(columns=YOY_METRIC_RENAMES)

    return ticker_series, ticker_metric_yoy


def _load_industry_series(repo: Repository) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sub-industry daily price series (with YoY merged in and the price
    index re-based to 100 at each sub-industry's first date) and
    sub-industry quarterly-metric YoY series."""
    industry_series = repo.fetch_dataframe(IndustryTimeSeries)
    industry_series_yoy = repo.fetch_dataframe(IndustryTimeSeriesYoY)
    industry_series = industry_series.merge(
        industry_series_yoy, on=["sub_industry", "date"], how="left"
    )
    industry_series = industry_series.sort_values(by=["sub_industry", "date"])

    # Re-base each sub-industry's indexed price series to 100 at its own
    # first observed date, so different sub-industries are comparable on
    # the same chart regardless of when their data starts.
    first_indexed_value = industry_series.groupby("sub_industry")[
        "industry_close_price_indexed"
    ].transform("first")
    industry_series["industry_close_price_indexed"] = (
        industry_series["industry_close_price_indexed"] / first_indexed_value * 100
    )

    industry_metrics_yoy = repo.fetch_dataframe(IndustryMetricsYoY)
    industry_metrics_yoy = industry_metrics_yoy.sort_values(by=["sub_industry", "date"])
    industry_metrics_yoy = industry_metrics_yoy.rename(columns=YOY_METRIC_RENAMES)

    return industry_series, industry_metrics_yoy


def _load_quarterly_financials(
    repo: Repository, company_info: pd.DataFrame, ticker_series_data: pd.DataFrame
) -> pd.DataFrame:
    """Quarterly financials joined with company info and a forward-filled
    close price (for P/E), with display-style column renames applied.

    Bug found while tracing the original: the original forward-filled
    `close_price` across the *entire* multi-ticker frame in one call,
    without grouping by ticker first —
    `qfin_ticker_data['close_price'] = qfin_ticker_data['close_price'].ffill()`.
    Because the frame is an outer merge of two per-ticker series, a ticker
    whose price series starts later (or has a gap) than the previous
    ticker's last row could silently forward-fill *that other ticker's*
    price into its own rows, corrupting the P/E ratio. Fixed by grouping
    the ffill by ticker; see the regression test in
    `tests/comparison_tool/test_data_loader.py` for a case that would have
    picked up a neighboring ticker's price under the old behaviour.
    """
    qfin = repo.fetch_dataframe(QuarterlyFinancialData)
    qfin = qfin.merge(company_info, on="ticker", how="left")

    price_lookup = qfin[["ticker", "date"]].merge(
        ticker_series_data[["ticker", "date", "close_price"]],
        on=["ticker", "date"],
        how="outer",
    )
    price_lookup = price_lookup.sort_values(["ticker", "date"])
    price_lookup["close_price"] = price_lookup.groupby("ticker")["close_price"].ffill()

    qfin = qfin.merge(
        price_lookup[["ticker", "date", "close_price"]], on=["ticker", "date"], how="left"
    )
    qfin = qfin.rename(columns=QUARTERLY_METRIC_RENAMES)
    qfin["Price Over EPS"] = qfin["close_price"] / qfin["Basic EPS"]

    return qfin


def _load_balance_sheet(repo: Repository, company_info: pd.DataFrame) -> pd.DataFrame:
    """Balance-sheet data joined with company info, with display-style
    column renames applied."""
    bs_data = repo.fetch_dataframe(BalanceSheetData)
    bs_data = bs_data.merge(company_info, on="ticker", how="left")
    bs_data = bs_data.rename(columns=BALANCE_SHEET_RENAMES)
    return bs_data


def _load_cashflow_map(repo: Repository) -> dict[str, pd.DataFrame]:
    """Per-ticker free-cash-flow history, sorted ascending by date and
    indexed on `date` (the discounted-cashflow page reads the *latest* row
    as `.iloc[-1]`, which requires ascending order, and does
    `.reset_index(names=['date'])`, which requires `date` to be the index —
    both preserved here to match what that page expects).

    Returned as a dict keyed by ticker rather than one merged frame, since
    the DCF page only ever looks up one ticker's history at a time — no
    need to carry every other ticker's rows along for a single calculation.
    """
    cashflow = repo.fetch_dataframe(CashflowStatementData)
    cashflow = cashflow.rename(columns=CASHFLOW_RENAMES)
    cashflow = cashflow.sort_values(["ticker", "date"])
    return {ticker: group.set_index("date") for ticker, group in cashflow.groupby("ticker")}
