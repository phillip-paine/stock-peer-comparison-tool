"""
Pure transforms for the non-stock asset universe (commodities, indices,
ETFs, FX). Replaces `RetrieveEconomicsData.retrieve_economic_data` and its
helper `_create_melted_dataframe`.

Two things fixed while tracing the original:

1. The original recovered each symbol from a joined column name like
   `"Close_GC=F"` via `k.split("e_")[1]` — relying on "e_" appearing at a
   fixed position inside the literal string "Close_", which only works
   because "Close_" happens to contain "e_" once. This version reads
   `raw["Close"]` directly off yfinance's actual 2-level column MultiIndex
   instead of parsing a flattened string.
2. YoY here reuses `compute_yoy_by_date` from `transforms/time_series.py`
   instead of the bespoke merge the original had (its 4th near-duplicate
   YoY implementation, after the ticker-price, industry-price, and
   ticker/industry-metric versions). The only intentional behavior
   difference: the original guarded the YoY denominator with
   `.clip(lower=1)`, this one uses "zero exactly -> 0% change" like every
   other YoY call in this codebase. That only matters for an asset trading
   at a fractional price near zero, which doesn't occur for the commodities/
   indices/ETFs/FX this pulls today.
"""
from __future__ import annotations

import pandas as pd

from .time_series import compute_yoy_by_date


def transform_asset_class_series(
    raw: pd.DataFrame,
    symbol_to_name: dict[str, str],
    name_to_asset_class: dict[str, str],
) -> pd.DataFrame:
    """Multi-symbol raw price history -> tidy DataFrame matching
    AssetClassTimeSeries: ticker, date, asset_class, close_price,
    close_price_indexed, close_price_yoy.
    """
    empty = pd.DataFrame(columns=[
        "ticker", "date", "asset_class", "close_price", "close_price_indexed", "close_price_yoy",
    ])
    if raw is None or raw.empty or "Close" not in raw.columns.get_level_values(0):
        return empty

    close = raw["Close"].rename(columns=symbol_to_name)
    close = close.bfill()

    tidy = close.reset_index().melt(id_vars=[close.index.name or close.reset_index().columns[0]],
                                     var_name="ticker", value_name="close_price")
    tidy = tidy.rename(columns={tidy.columns[0]: "date"})
    tidy["date"] = pd.to_datetime(tidy["date"]).dt.date
    tidy["asset_class"] = tidy["ticker"].map(name_to_asset_class)
    tidy = tidy.dropna(subset=["close_price"])

    tidy = _add_indexed_column(tidy, group_col="ticker", date_col="date", value_col="close_price")

    yoy = compute_yoy_by_date(
        tidy, group_cols=["ticker"], date_col="date", value_cols=["close_price"], suffix="_yoy",
    )
    if not yoy.empty:
        yoy["date"] = pd.to_datetime(yoy["date"]).dt.date
    result = tidy.merge(yoy[["ticker", "date", "close_price_yoy"]], on=["ticker", "date"], how="left")

    return result[["ticker", "date", "asset_class", "close_price", "close_price_indexed", "close_price_yoy"]]


def _add_indexed_column(
    df: pd.DataFrame, group_col: str, date_col: str, value_col: str, out_col: str = "close_price_indexed",
) -> pd.DataFrame:
    """Index each group's series to 100 at its earliest date."""
    df = df.sort_values([group_col, date_col]).copy()
    first_values = df.groupby(group_col)[value_col].transform("first")
    df[out_col] = df[value_col] / first_values * 100
    return df
