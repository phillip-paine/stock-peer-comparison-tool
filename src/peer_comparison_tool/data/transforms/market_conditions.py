"""
Macro asset-class moves -- pure, DB-free.

Feeds the market conditions page: a "what's moved recently" table across
every tracked non-stock asset (commodities, indices, ETFs, FX, and Treasury
yields -- see the new `"rate"` group in `constants.ASSET_CLASS_TICKERS`),
computed from `AssetClassTimeSeries` (already loaded once at dashboard
startup as `economic_data` -- see `data_loader.py`). No new data needed for
this part; it's the same table the landing page already charts, just
summarized as % moves instead of plotted as a time series.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

# Trading-day lookback windows, not calendar days -- consistent with how
# price history is treated everywhere else in this codebase (e.g.
# `compute_yoy_by_date`'s exact-calendar-date matching is the one deliberate
# exception, for a different reason: matching a specific prior year's date).
MOVE_WINDOWS = {"1d": 1, "1w": 5, "1m": 21}


def compute_asset_moves(
    asset_class_time_series: pd.DataFrame, windows: dict[str, int] = MOVE_WINDOWS
) -> list[dict[str, Any]]:
    """Latest price plus % change over each window in `windows`, one row
    per ticker in `asset_class_time_series` (the friendly display name --
    e.g. `"US10Y_Yield"` -- not the raw yfinance symbol; see
    `transform_asset_class_series`).

    A ticker with fewer rows than a given window's lookback gets `None`
    for that window rather than an error or a misleadingly-computed change
    over less history than the label implies (e.g. a recently-added asset
    class ticker with only 10 days of history gets `None` for `"1m"`, not
    a "1-month change" actually computed over 10 days).
    """
    if asset_class_time_series.empty:
        return []

    rows = []
    for ticker, group in asset_class_time_series.groupby("ticker"):
        g = group.sort_values("date")
        close = g["close_price"].dropna()
        if close.empty:
            continue

        latest_price = close.iloc[-1]
        row: dict[str, Any] = {
            "ticker": ticker,
            "asset_class": g["asset_class"].iloc[-1],
            "latest_date": g["date"].iloc[-1],
            "latest_price": latest_price,
        }
        for label, n in windows.items():
            if len(close) > n and close.iloc[-(n + 1)]:
                prior_price = close.iloc[-(n + 1)]
                row[f"change_{label}"] = (latest_price / prior_price) - 1
            else:
                row[f"change_{label}"] = None
        rows.append(row)

    return rows
