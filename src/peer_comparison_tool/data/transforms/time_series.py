"""
Pure, DB-free time series transforms.

These replace the aggregation logic that was previously written three times
as near-identical raw SQL / inline pandas blocks:

- `query_ticker_time_series_yoy` (SQL, daily ticker price YoY)
- `query_create_industry_price_yoy_aggregation` (SQL, daily industry price YoY)
- the `df_quarter`/`df_quarter_lagged` block duplicated in both
  `update_ticker_yoy_aggregations` and `update_industry_aggregations`
  (quarterly metric YoY, ticker- and industry-level)

Two matching strategies are needed because daily price series and quarterly
financial reports don't line up the same way:

- Daily series (`compute_yoy_by_date`): match on the exact calendar date one
  year prior. This mirrors the original SQL's exact-date join, including its
  limitation — a date that isn't a trading day both this year and last year
  won't have a match, so some rows are dropped rather than approximated.
- Quarterly reports (`compute_yoy_by_quarter`): match on the same fiscal
  quarter one calendar year prior (e.g. "2026_1" against "2025_1"), since
  actual report dates drift quarter to quarter and won't line up to the day.

All functions here only take/return DataFrames — nothing touches the
database, so they're tested directly with plain pandas fixtures.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


def compute_yoy_by_date(
    df: pd.DataFrame,
    group_cols: Sequence[str],
    date_col: str,
    value_cols: Sequence[str],
    suffix: str = "_yoy",
) -> pd.DataFrame:
    """Percentage change vs. the same group's value on the exact same
    calendar date one year earlier.

    Rows with no exact match one year prior are dropped (inner join),
    matching the original SQL's behavior.
    """
    empty_cols = [*group_cols, date_col, *(f"{c}{suffix}" for c in value_cols)]
    if df.empty:
        return pd.DataFrame(columns=empty_cols)

    current = df[[*group_cols, date_col, *value_cols]].copy()
    current[date_col] = pd.to_datetime(current[date_col])

    # Shifting a row's date forward one year means: when this shifted row is
    # matched against `current` on date, the match represents "this exact
    # data point, but from one year before the matched current date."
    prior = current.copy()
    prior[date_col] = prior[date_col] + pd.DateOffset(years=1)
    prior = prior.rename(columns={c: f"{c}__prior" for c in value_cols})

    merged = pd.merge(current, prior, on=[*group_cols, date_col], how="inner")
    if merged.empty:
        return pd.DataFrame(columns=empty_cols)

    result = merged[[*group_cols, date_col]].copy()
    for col in value_cols:
        result[f"{col}{suffix}"] = _safe_pct_change(merged[col], merged[f"{col}__prior"])
    return result


def compute_yoy_by_quarter(
    df: pd.DataFrame,
    group_cols: Sequence[str],
    quarter_col: str,
    date_col: str,
    value_cols: Sequence[str],
    suffix: str = "_yoy",
) -> pd.DataFrame:
    """Percentage change vs. the same group's value in the same fiscal
    quarter one calendar year earlier. `quarter_col` values are expected in
    "{year}_{quarter}" form, e.g. "2026_1" (as produced when quarterly
    reports are ingested).
    """
    empty_cols = [*group_cols, date_col, quarter_col, *(f"{c}{suffix}" for c in value_cols)]
    if df.empty:
        return pd.DataFrame(columns=empty_cols)

    working = df.copy()
    year_quarter = working[quarter_col].str.split("_", n=1, expand=True)
    working["_year"] = year_quarter[0].astype(int)
    working["_quarter_num"] = year_quarter[1]

    current = working[[*group_cols, date_col, quarter_col, "_year", "_quarter_num", *value_cols]]
    prior = current.copy()
    prior["_year"] = prior["_year"] + 1  # see compute_yoy_by_date for the shift-forward rationale
    prior = prior.rename(columns={c: f"{c}__prior" for c in value_cols})
    prior = prior[[*group_cols, "_year", "_quarter_num", *(f"{c}__prior" for c in value_cols)]]

    merged = pd.merge(current, prior, on=[*group_cols, "_year", "_quarter_num"], how="inner")
    if merged.empty:
        return pd.DataFrame(columns=empty_cols)

    result = merged[[*group_cols, date_col, quarter_col]].copy()
    for col in value_cols:
        result[f"{col}{suffix}"] = _safe_pct_change(merged[col], merged[f"{col}__prior"])
    return result


def aggregate_sum(df: pd.DataFrame, group_cols: Sequence[str], value_cols: Sequence[str]) -> pd.DataFrame:
    """Sum `value_cols` within each group. Used to roll ticker-level price
    series up to a sub-industry total (industry_time_series)."""
    if df.empty:
        return pd.DataFrame(columns=[*group_cols, *value_cols])
    return df.groupby(list(group_cols), as_index=False)[list(value_cols)].sum()


def aggregate_mean_by_quarter(
    df: pd.DataFrame,
    group_cols: Sequence[str],
    quarter_col: str,
    date_col: str,
    value_cols: Sequence[str],
) -> pd.DataFrame:
    """Average `value_cols` within each group + quarter, taking the earliest
    `date_col` in the group as the representative date. Used to roll
    per-ticker quarterly financials up to a sub-industry average
    (industry_metrics)."""
    if df.empty:
        return pd.DataFrame(columns=[*group_cols, date_col, quarter_col, *value_cols])
    agg = {date_col: "min", **{c: "mean" for c in value_cols}}
    return df.groupby([*group_cols, quarter_col], as_index=False).agg(agg)


def _safe_pct_change(current: pd.Series, prior: pd.Series) -> pd.Series:
    """(current / prior - 1) * 100, with a zero (not inf/NaN) result where
    `prior` is exactly zero — matching the original SQL/pandas behavior."""
    return np.where(prior != 0, (current / prior - 1) * 100, 0.0)
