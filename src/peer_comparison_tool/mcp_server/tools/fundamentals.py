"""Fundamentals tools: quarterly income statement metrics, balance sheet, cash flow.

Values are returned exactly as the pipeline stored them. The units below were
read off `data/transforms/ticker_financials.py`, not assumed -- two of the
balance-sheet columns do not mean what their names suggest.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ...data.models import (
    BalanceSheetData,
    CashflowStatementData,
    QuarterlyFinancialData,
    QuarterlyFinancialDataYoY,
)
from ..read_repository import ReadRepository
from ..serialize import clamp, df_records, to_jsonable
from .reference import resolve_company

MAX_PERIODS = 40

QUARTERLY_NOTES = [
    "gross_margin / operating_margin / net_margin / ebitda_margin are PERCENT (25.0 means 25%).",
    "operating_income_mm / net_income_mm are millions; operating_income / net_income are raw currency units.",
    "*_yoy columns compare with the same fiscal quarter a year earlier (null until a year of history exists).",
]
BALANCE_SHEET_NOTES = [
    "Pipeline definitions (the column names are misleading): quick_ratio = (current_assets - inventory) / "
    "TOTAL liabilities (or current_assets / total liabilities if inventory is missing), not the textbook "
    "current-liabilities version; equity_ratio = (current_assets - total liabilities) / ordinary_shares_number, "
    "i.e. a per-share amount, NOT equity / assets; debt_to_equity_ratio = total liabilities / stockholders_equity "
    "(a plain ratio, 1.5 = 1.5x), so it is not comparable with the valuation snapshot's debt_to_equity_ratio.",
    "Companies reporting on a non-standard balance-sheet template (e.g. banks) can have zeros/nulls here.",
]
CASH_FLOW_NOTES = ["Raw currency units as stored (not millions)."]


def _series(repo: ReadRepository, model: Any, ticker: str, periods: int) -> pd.DataFrame:
    return repo.recent_rows(model, clamp(periods, 1, MAX_PERIODS), ticker=ticker)


def _response(info: dict[str, Any], df: pd.DataFrame, notes: list[str]) -> dict[str, Any]:
    columns = [c for c in df.columns if c != "ticker"]
    return to_jsonable({
        "ticker": info["ticker"],
        "name": info["name"],
        "periods": int(len(df)),
        "as_of": df["date"].max() if not df.empty else None,
        "rows": df_records(df, columns),
        "notes": notes,
    })


def quarterly_financials(
    repo: ReadRepository, ticker: str, quarters: int = 8, include_yoy: bool = True
) -> dict[str, Any]:
    """Last `quarters` reported quarters of EPS, income and margins, oldest first."""
    info = resolve_company(repo, ticker)
    df = _series(repo, QuarterlyFinancialData, info["ticker"], quarters)
    if include_yoy and not df.empty:
        yoy = repo.fetch_dataframe(QuarterlyFinancialDataYoY, ticker=info["ticker"])
        if not yoy.empty:
            yoy = yoy.assign(date=pd.to_datetime(yoy["date"])).drop(columns=["ticker", "quarter_reporting"])
            df = df.merge(yoy, on="date", how="left")
    return _response(info, df, QUARTERLY_NOTES)


def balance_sheet(repo: ReadRepository, ticker: str, periods: int = 4) -> dict[str, Any]:
    """Last `periods` annual balance-sheet rows, oldest first."""
    info = resolve_company(repo, ticker)
    return _response(info, _series(repo, BalanceSheetData, info["ticker"], periods), BALANCE_SHEET_NOTES)


def cash_flow(repo: ReadRepository, ticker: str, periods: int = 4) -> dict[str, Any]:
    """Last `periods` cash-flow statement rows, oldest first."""
    info = resolve_company(repo, ticker)
    return _response(info, _series(repo, CashflowStatementData, info["ticker"], periods), CASH_FLOW_NOTES)
