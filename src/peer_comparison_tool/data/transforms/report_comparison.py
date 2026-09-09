"""
Latest-vs-prior period comparison -- pure, DB-free.

Feeds a new page: pick a ticker, pick quarterly or annual, see a table of
metric / latest value / prior value (plus % change) for that one ticker,
alongside a link out to that ticker's SEC filings. Distinct from
`company_quarterly_report_page.py`, which plots one metric over time across
many tickers -- this is a single-ticker snapshot comparison, not a chart.

Operates on the same frames `data_loader.py` already builds at startup:

- Quarterly mode reads `qfin_data` (from `QuarterlyFinancialData` --
  `quarter_reporting` labels like `"2024_3"`).
- Annual mode reads a frame built by `build_annual_frame()` below, which
  merges `bs_data` (from `BalanceSheetData` -- `annual_reporting` labels
  like `"2024"`) with that ticker's cashflow history out of `cashflow_map`
  (from `CashflowStatementData`, which has no period label of its own --
  see `build_annual_frame`'s docstring for how the two are matched up).

Both `BalanceSheetData` and `CashflowStatementData` are annual-cadence only
in the current pipeline (yfinance's default `get_balance_sheet()`/
`cashflow` calls, not the quarterly variants) -- so "annual" mode is the
only option for those metrics today. Fine per Phillip's call; quarterly
balance-sheet/cashflow would need `fetch_quarterly_balance_sheet`/
`fetch_quarterly_cashflow` added to `YFinanceClient` and re-ingesting,
which is a pipeline change, not something this page can work around.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

# Column name -> display label. Kept here (not hardcoded in the page) so the
# metric checklist and the table header can share one source of truth.
QUARTERLY_METRIC_LABELS = {
    "Basic EPS": "Basic EPS",
    "Price Over EPS": "P/E (Price / EPS)",
    "operating_income": "Operating Income",
    "operating_income_mm": "Operating Income ($MM)",
    "net_income": "Net Income",
    "net_income_mm": "Net Income ($MM)",
    "Gross Margin": "Gross Margin",
    "Operating Margin": "Operating Margin",
    "Net Margin": "Net Margin",
    "EBITDA Margin": "EBITDA Margin",
}

ANNUAL_METRIC_LABELS = {
    "ordinary_shares_number": "Shares Outstanding",
    "stockholders_equity": "Stockholders' Equity",
    "total_liabilities_net_minority_interest": "Total Liabilities",
    "current_assets": "Current Assets",
    "Quick Ratio": "Quick Ratio",
    "Equity Ratio": "Equity Ratio",
    "Debt-to-Equity Ratio": "Debt-to-Equity Ratio",
    "Free Cash Flow": "Free Cash Flow",
    "operating_cash_flow": "Operating Cash Flow",
    "capital_expenditure": "Capital Expenditure",
}

# Metrics whose value is a ratio/margin already expressed as a fraction
# (0.34, not 34) -- shown as a percentage in the table. Everything else in
# the two label maps above is either a per-share number, a multiple, or a
# raw dollar/share count, shown as a plain number.
PERCENT_METRICS = {"Gross Margin", "Operating Margin", "Net Margin", "EBITDA Margin"}

# Large dollar or share-count figures -- shown with thousands separators and
# no decimal places. Classified by metric name rather than by inspecting the
# Python type of the value: a mixed-dtype DataFrame row (strings alongside
# numbers, as every row here is -- ticker, period label, metric values) comes
# back as an object-dtype Series where numeric cells are numpy scalar types
# (`numpy.int64`, `numpy.float64`), not plain Python `int`/`float` --
# `isinstance(value, (int, float))` silently fails on those and would drop
# comma formatting entirely, so this doesn't attempt that check at all.
LARGE_NUMBER_METRICS = {
    "operating_income", "operating_income_mm", "net_income", "net_income_mm",
    "stockholders_equity", "total_liabilities_net_minority_interest", "current_assets",
    "ordinary_shares_number", "Free Cash Flow", "operating_cash_flow", "capital_expenditure",
}

# Metrics where a *decrease* is the favourable direction -- lower leverage is
# healthier, so a negative change here should read as good news (green), not
# bad (red), the opposite of every other metric in the two label maps above.
# Deliberately narrow: e.g. "Total Liabilities" or "capital_expenditure"
# falling isn't unambiguously good (could mean a shrinking business or less
# growth investment rather than improved health), so they're left with the
# default positive-is-green coloring rather than guessed at.
INVERTED_COLOR_METRICS = {"Debt-to-Equity Ratio"}


def build_annual_frame(bs_data: pd.DataFrame, cashflow_map: dict[str, pd.DataFrame], ticker: str) -> pd.DataFrame:
    """One row per annual period for `ticker`, combining `bs_data` (has the
    `annual_reporting` period label) with that ticker's cashflow history
    from `cashflow_map` (indexed by `date`, no period label of its own).

    Matched on `date` -- both come from yfinance's annual statements for
    the same ticker, so the same fiscal-period-end date is expected on
    both sides. A cashflow-only row (no matching balance-sheet date) still
    gets a period label, falling back to that row's calendar year rather
    than being dropped.
    """
    bs = bs_data[bs_data["ticker"] == ticker].copy() if not bs_data.empty else pd.DataFrame()
    cashflow = cashflow_map.get(ticker, pd.DataFrame())
    cashflow = cashflow.reset_index() if not cashflow.empty else cashflow

    if bs.empty and cashflow.empty:
        return pd.DataFrame()
    if bs.empty:
        merged = cashflow.copy()
        merged["annual_reporting"] = None
    elif cashflow.empty:
        merged = bs.copy()
    else:
        merged = bs.merge(cashflow, on="date", how="outer")

    if "annual_reporting" not in merged.columns:
        merged["annual_reporting"] = None
    missing_label = merged["annual_reporting"].isna()
    merged.loc[missing_label, "annual_reporting"] = merged.loc[missing_label, "date"].apply(
        lambda d: str(d.year) if pd.notna(d) else None
    )

    return merged.sort_values("date")


def latest_two_periods(df: pd.DataFrame, ticker: str, date_col: str = "date") -> pd.DataFrame:
    """The most recent two rows for `ticker`, oldest first.

    `df` is assumed already filtered to one ticker (as `build_annual_frame`
    returns) or is filtered here if it still has a `ticker` column (as the
    raw `qfin_data` frame does).
    """
    if "ticker" in df.columns:
        df = df[df["ticker"] == ticker]
    return df.sort_values(date_col).tail(2)


def build_comparison_table(
    df: pd.DataFrame, ticker: str, metrics: list[str], period_col: str, date_col: str = "date"
) -> list[dict[str, Any]]:
    """Metric / latest value / prior value / % change, for whichever of
    `metrics` are present in `df`'s columns.

    A ticker with only one period of history still gets a row per metric
    (prior fields `None`) rather than being dropped entirely -- a recent
    IPO or thin history shouldn't just disappear from the page. `%% change`
    is only computed when both values are present and the prior value is
    non-zero (a zero-based percentage change is undefined, not "infinite%
    growth").
    """
    latest_two = latest_two_periods(df, ticker, date_col)
    if latest_two.empty:
        return []

    latest_row = latest_two.iloc[-1]
    prior_row = latest_two.iloc[-2] if len(latest_two) > 1 else None

    rows = []
    for metric in metrics:
        if metric not in df.columns:
            continue
        latest_value = latest_row.get(metric)
        prior_value = prior_row.get(metric) if prior_row is not None else None

        change_pct = None
        if pd.notna(latest_value) and prior_value is not None and pd.notna(prior_value) and prior_value != 0:
            change_pct = (latest_value - prior_value) / abs(prior_value)

        rows.append({
            "metric": metric,
            "latest_period": latest_row.get(period_col),
            "latest_value": None if pd.isna(latest_value) else latest_value,
            "prior_period": prior_row.get(period_col) if prior_row is not None else None,
            "prior_value": None if (prior_value is None or pd.isna(prior_value)) else prior_value,
            "change_pct": change_pct,
        })
    return rows
