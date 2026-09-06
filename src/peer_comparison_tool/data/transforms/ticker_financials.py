"""
Pure transforms for per-ticker data: quarterly financials, balance sheet,
cashflow, price history, and company overview/metrics. Every function here
takes raw yfinance output (as returned by YFinanceClient) and a ticker, and
returns a tidy DataFrame or dict shaped to match the corresponding ORM model
in `data/models.py`. Nothing here touches the network or the database.

Replaces the transformation methods on `RetrieveStockData`:
`get_quarterly_financials_app_data`, `get_balance_sheet_app_data`,
`get_cashflow_data`, `get_stock_level_data`, `_retrieve_recent_metrics`.

Two behavioral fixes made while tracing the original:

1. **Quick Ratio bug**: the original only computed `Quick Ratio` inside the
   `else` branch of the `TotalLiabilitiesNetMinorityInterest` presence
   check — meaning any ticker that needed `TotalLiabilitiesNetMinorityInterest`
   synthesized (typically financial institutions) never got a Quick Ratio at
   all, silently. This version computes it unconditionally, from whichever
   `TotalLiabilitiesNetMinorityInterest` value is available (given or
   synthesized).
2. **Fragile ticker-name recovery**: not in this module (see
   `asset_classes.py`), but a related fragile string-split pattern from the
   original economics retriever is fixed there too.
3. **Missing StockholdersEquity/OrdinarySharesNumber crashed the whole
   pipeline run**: some tickers (financial institutions especially --
   confirmed pulling the "Financials" sector) don't report these under
   their usual names, and unlike `CurrentAssets`/
   `TotalLiabilitiesNetMinorityInterest` a few lines above, there was no
   fallback for them at all -- a plain `KeyError` on one ticker used to
   propagate all the way up and abort the entire batch, discarding every
   other ticker already fetched in that run. Now falls back to known
   alternate line items (`TotalEquityGrossMinorityInterest`/
   `CommonStockEquity` for equity, `ShareIssued` for share count), then to
   0 if genuinely none of those are present either -- same degrade-not-crash
   behavior the two fields above already had. Those particular alternate
   column names are a best-effort guess at yfinance's naming for
   non-standard reporters, not verified against a live pull; if a specific
   ticker still comes back with the wrong ratio, print `raw.index` for that
   ticker's `balance_sheet_raw` to see its actual field names and adjust
   the fallback chain here.
"""
from __future__ import annotations

from datetime import date as date_type

import numpy as np
import pandas as pd

QUARTERLY_SOURCE_ROWS = ["Basic EPS", "Operating Income", "Total Revenue", "Gross Profit", "Net Income", "EBITDA"]
CASHFLOW_COLUMNS = ["Free Cash Flow", "Operating Cash Flow", "Capital Expenditure"]


def transform_quarterly_financials(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Quarterly income-statement metrics -> tidy DataFrame matching
    QuarterlyFinancialData: ticker, date, quarter_reporting, basic_eps,
    operating_income, operating_income_mm, net_income, net_income_mm,
    gross_margin, operating_margin, net_margin, ebitda_margin.

    Falls back to related line items where a metric isn't reported directly
    (e.g. Diluted EPS standing in for Basic EPS, Net Interest Income
    standing in for Gross Profit at banks), same as the original.
    """
    if raw is None or raw.empty:
        return _empty_quarterly_financials()

    df = raw.copy()
    rows = df.index.to_list()

    df = _fallback_row(df, rows, target="Basic EPS", fallback="Diluted EPS")
    df = _fallback_row(df, rows, target="EBITDA", fallback="EBIT")
    df = _fallback_row(df, rows, target="Operating Income", fallback="EBIT")
    if "Gross Profit" not in rows:
        # Banks typically don't report COGS/Gross Profit; Net Interest Income
        # is the closest analogous line item.
        df = _fallback_row(df, rows, target="Gross Profit", fallback="Net Interest Income")

    try:
        df = df.loc[QUARTERLY_SOURCE_ROWS]
    except KeyError:
        return _empty_quarterly_financials()

    df = df.astype(float).fillna(0.0).transpose()

    df["Gross Margin"] = np.where(df["Total Revenue"] > 0, df["Gross Profit"] / df["Total Revenue"] * 100, 0.0)
    df["Operating Margin"] = np.where(df["Total Revenue"] > 0, df["Operating Income"] / df["Total Revenue"] * 100, 0.0)
    df["Net Margin"] = np.where(df["Total Revenue"] > 0, df["Net Income"] / df["Total Revenue"] * 100, 0.0)
    df["EBITDA Margin"] = np.where(df["Total Revenue"] > 0, df["EBITDA"] / df["Total Revenue"] * 100, 0.0)

    df = df.drop(columns=["Total Revenue", "Gross Profit", "EBITDA"])
    df = df.reset_index().rename(columns={"index": "date"})
    df["date"] = pd.to_datetime(df["date"])

    # Reporting dates for the same fiscal quarter can land on slightly
    # different days year to year; shifting back a month before deriving the
    # quarter label smooths that out (e.g. a report dated just after a
    # quarter boundary still maps to the quarter it's reporting on).
    date_moved = df["date"] - pd.DateOffset(months=1)
    df["quarter_reporting"] = date_moved.dt.year.astype(str) + "_" + date_moved.dt.quarter.astype(str)

    df["ticker"] = ticker
    df["date"] = df["date"].dt.date
    df["operating_income_mm"] = df["Operating Income"] / 1_000_000
    df["net_income_mm"] = df["Net Income"] / 1_000_000

    df = df.rename(columns={
        "Basic EPS": "basic_eps",
        "Operating Income": "operating_income",
        "Net Income": "net_income",
        "Gross Margin": "gross_margin",
        "Operating Margin": "operating_margin",
        "Net Margin": "net_margin",
        "EBITDA Margin": "ebitda_margin",
    })
    return df[[
        "ticker", "date", "quarter_reporting", "basic_eps", "operating_income", "operating_income_mm",
        "net_income", "net_income_mm", "gross_margin", "operating_margin", "net_margin", "ebitda_margin",
    ]]


def transform_balance_sheet(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Annual balance sheet -> tidy DataFrame matching BalanceSheetData:
    ticker, date, annual_reporting, ordinary_shares_number,
    stockholders_equity, total_liabilities_net_minority_interest,
    current_assets, quick_ratio, equity_ratio, debt_to_equity_ratio.
    """
    if raw is None or raw.empty:
        return _empty_balance_sheet()

    df = raw.astype(float).fillna(0.0).transpose()

    if "CurrentAssets" not in df.columns:
        # Financial institutions don't report CurrentAssets directly; build
        # an equivalent from cash + receivables + loans.
        zeros = pd.Series(0.0, index=df.index)
        df["CurrentAssets"] = (
                df.get("CashCashEquivalentsAndShortTermInvestments", df.get("CashAndCashEquivalents", zeros))
                + df.get("Receivables", zeros)
                + df.get("TotalLoans", df.get("LoansReceivables", zeros))
        )

    if "TotalLiabilitiesNetMinorityInterest" not in df.columns:
        zeros = pd.Series(0.0, index=df.index)
        df["TotalLiabilitiesNetMinorityInterest"] = (
                df.get("TotalDeposits", df.get("CustomerDeposits", zeros))
                + df.get("UnearnedPremium", zeros)
                + df.get("AccountsPayable", zeros)
        )

    # Computed unconditionally regardless of whether TotalLiabilitiesNetMinorityInterest
    # was reported directly or synthesized above — see module docstring for
    # why this differs from the original.
    if "Inventory" in df.columns:
        df["Quick Ratio"] = (df["CurrentAssets"] - df["Inventory"]) / df["TotalLiabilitiesNetMinorityInterest"]
    else:
        df["Quick Ratio"] = df["CurrentAssets"] / df["TotalLiabilitiesNetMinorityInterest"]

    # StockholdersEquity and OrdinarySharesNumber can be absent for the same
    # reason CurrentAssets/TotalLiabilitiesNetMinorityInterest can be above
    # (financial institutions reporting on a different balance sheet
    # template) -- confirmed in practice by a crash pulling the Financials
    # sector. Same fallback approach: try known alternate line items yfinance
    # sometimes uses instead, and fall back to 0 (not a raised error) if none
    # are present, consistent with how the two fields above already degrade.
    zeros = pd.Series(0.0, index=df.index)
    if "StockholdersEquity" not in df.columns:
        df["StockholdersEquity"] = df.get("TotalEquityGrossMinorityInterest", df.get("CommonStockEquity", zeros))
    if "OrdinarySharesNumber" not in df.columns:
        df["OrdinarySharesNumber"] = df.get("ShareIssued", zeros)

    df["Equity Ratio"] = (df["CurrentAssets"] - df["TotalLiabilitiesNetMinorityInterest"]) / df["OrdinarySharesNumber"]
    df["Debt-to-Equity Ratio"] = df["TotalLiabilitiesNetMinorityInterest"] / df["StockholdersEquity"]

    df = df.reset_index().rename(columns={"index": "date"})
    df["date"] = pd.to_datetime(df["date"])

    date_moved = df["date"] + pd.DateOffset(months=3)
    df["annual_reporting"] = date_moved.dt.year.astype(str)

    df["ticker"] = ticker
    df["date"] = df["date"].dt.date

    df = df.rename(columns={
        "OrdinarySharesNumber": "ordinary_shares_number",
        "StockholdersEquity": "stockholders_equity",
        "TotalLiabilitiesNetMinorityInterest": "total_liabilities_net_minority_interest",
        "CurrentAssets": "current_assets",
        "Quick Ratio": "quick_ratio",
        "Equity Ratio": "equity_ratio",
        "Debt-to-Equity Ratio": "debt_to_equity_ratio",
    })
    return df[[
        "ticker", "date", "annual_reporting", "ordinary_shares_number", "stockholders_equity",
        "total_liabilities_net_minority_interest", "current_assets", "quick_ratio",
        "equity_ratio", "debt_to_equity_ratio",
    ]]


def transform_cashflow(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Cashflow statement -> tidy DataFrame matching CashflowStatementData:
    ticker, date, free_cash_flow, operating_cash_flow, capital_expenditure.
    """
    if raw is None or raw.empty:
        return _empty_cashflow()

    df = raw.transpose().sort_index()
    for col in CASHFLOW_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan

    df = df[CASHFLOW_COLUMNS].reset_index().rename(columns={"index": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["ticker"] = ticker

    df = df.rename(columns={
        "Free Cash Flow": "free_cash_flow",
        "Operating Cash Flow": "operating_cash_flow",
        "Capital Expenditure": "capital_expenditure",
    })
    return df[["ticker", "date", "free_cash_flow", "operating_cash_flow", "capital_expenditure"]]


def transform_price_history(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Daily price history -> tidy DataFrame matching TickerTimeSeries:
    ticker, date, close_price, close_price_indexed."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["ticker", "date", "close_price", "close_price_indexed"])

    df = raw.reset_index()
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    df["date"] = pd.to_datetime(df[date_col]).dt.tz_localize(None).dt.date
    df["close_price"] = df["Close"]
    df["close_price_indexed"] = df["Close"] / df["Close"].iloc[0] * 100
    df["ticker"] = ticker
    return df[["ticker", "date", "close_price", "close_price_indexed"]]


def transform_company_info(info: dict, ticker: str, name: str, sub_industry: str) -> dict | None:
    """`Ticker.info` -> dict matching CompanyInfo. Returns None if `info`
    has no sector — the original silently skipped any ticker without one,
    treating it as an invalid/delisted symbol."""
    sector = info.get("sector")
    if not sector:
        return None
    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "industry": info.get("industry"),
        "sub_industry": sub_industry,
    }


def transform_recent_metrics(info: dict, ticker: str) -> dict:
    """`Ticker.info` -> dict matching TickerMostRecentMetric."""
    trailing_pe = info.get("trailingPE")
    trailing_pe = np.inf if trailing_pe == "Infinity" else trailing_pe

    latest_eps = None
    net_income_to_common = info.get("netIncomeToCommon")
    shares_outstanding = info.get("sharesOutstanding")
    if net_income_to_common is not None and shares_outstanding:
        latest_eps = net_income_to_common / shares_outstanding

    return {
        "ticker": ticker,
        "market_cap": info.get("marketCap"),
        "price_eps_ratio": _round_or_none(trailing_pe),
        "price_to_book": _round_or_none(info.get("priceToBook")),
        "return_on_equity": _round_or_none(info.get("returnOnEquity")),
        "debt_to_equity_ratio": _round_or_none(info.get("debtToEquity")),
        "profit_margin": _round_or_none(info.get("profitMargins")),
        "enterprise_to_ebitda": _round_or_none(info.get("enterpriseToEbitda")),
        "latest_eps": _round_or_none(latest_eps),
        "enterprise_value": _round_or_none(info.get("enterpriseValue")),
    }


def _fallback_row(df: pd.DataFrame, existing_rows: list[str], target: str, fallback: str) -> pd.DataFrame:
    if target in existing_rows:
        return df
    df = df.copy()
    df.loc[target] = df.loc[fallback] if fallback in existing_rows else float(np.nan)
    return df


def _round_or_none(value, decimals: int = 2):
    return round(value, decimals) if value is not None else None


def _empty_quarterly_financials() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "ticker", "date", "quarter_reporting", "basic_eps", "operating_income", "operating_income_mm",
        "net_income", "net_income_mm", "gross_margin", "operating_margin", "net_margin", "ebitda_margin",
    ])


def _empty_balance_sheet() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "ticker", "date", "annual_reporting", "ordinary_shares_number", "stockholders_equity",
        "total_liabilities_net_minority_interest", "current_assets", "quick_ratio",
        "equity_ratio", "debt_to_equity_ratio",
    ])


def _empty_cashflow() -> pd.DataFrame:
    return pd.DataFrame(columns=["ticker", "date", "free_cash_flow", "operating_cash_flow", "capital_expenditure"])