"""Tests for `compute_asset_moves` (the Macro Moves table's data)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from peer_comparison_tool.data.transforms.market_conditions import compute_asset_moves


def _series(ticker: str, closes: list[float | None], asset_class: str | None = "commodity",
            start: date = date(2026, 1, 1)) -> pd.DataFrame:
    return pd.DataFrame({
        "ticker": ticker,
        "date": [start + timedelta(days=i) for i in range(len(closes))],
        "asset_class": asset_class,
        "close_price": closes,
    })


def _by_ticker(rows):
    return {r["ticker"]: r for r in rows}


def test_empty_frame_returns_empty_list():
    assert compute_asset_moves(pd.DataFrame()) == []


def test_computes_percent_change_over_each_window():
    closes = [100.0 + i for i in range(30)]  # 100..129
    row = _by_ticker(compute_asset_moves(_series("Gold", closes)))["Gold"]
    assert row["latest_price"] == 129.0
    assert np.isclose(row["change_1d"], 129 / 128 - 1)
    assert np.isclose(row["change_1w"], 129 / 124 - 1)
    assert np.isclose(row["change_1m"], 129 / 108 - 1)
    assert row["asset_class"] == "commodity"


def test_short_history_gets_none_not_a_misleading_change():
    row = _by_ticker(compute_asset_moves(_series("New", [10.0 + i for i in range(10)])))["New"]
    assert row["change_1d"] is not None and row["change_1w"] is not None
    assert row["change_1m"] is None  # only 10 observations; a 21-day change can't be computed


def test_unsorted_input_is_sorted_by_date_per_ticker():
    df = _series("Gold", [100.0, 101.0, 102.0]).iloc[::-1]
    row = _by_ticker(compute_asset_moves(df))["Gold"]
    assert row["latest_price"] == 102.0


def test_latest_date_is_the_date_of_the_latest_price_not_a_trailing_nan_row():
    """Regression: `latest_date` used to come from the raw rows while the
    price came from the NaN-dropped series, so a trailing NaN close made the
    reported date a day later than the price it labelled."""
    df = _series("Gold", [100.0, 101.0, np.nan], start=date(2026, 3, 1))
    row = _by_ticker(compute_asset_moves(df))["Gold"]
    assert row["latest_price"] == 101.0
    assert row["latest_date"] == date(2026, 3, 2)


def test_all_nan_ticker_is_skipped():
    df = pd.concat([_series("Dead", [np.nan, np.nan]), _series("Live", [1.0, 2.0])])
    assert set(_by_ticker(compute_asset_moves(df))) == {"Live"}


def test_missing_asset_class_falls_back_to_known_mapping_then_unknown():
    """Rows written before the AssetClass backfill have NULL asset_class;
    the table should still group sensibly (and sort -- None vs str can't be
    compared) rather than crash or show 'None'."""
    from peer_comparison_tool.data.constants import asset_name_to_class

    known_name, known_class = next(iter(asset_name_to_class().items()))
    df = pd.concat([
        _series(known_name, [1.0, 2.0], asset_class=None),
        _series("NotInConstants", [1.0, 2.0], asset_class=None),
    ])
    rows = _by_ticker(compute_asset_moves(df))
    assert rows[known_name]["asset_class"] == known_class
    assert rows["NotInConstants"]["asset_class"] == "Unknown"
    assert all(isinstance(r["asset_class"], str) for r in rows.values())


def test_uses_last_non_null_asset_class_when_some_rows_are_null():
    df = _series("Gold", [1.0, 2.0, 3.0], asset_class="commodity")
    df.loc[2, "asset_class"] = None
    assert _by_ticker(compute_asset_moves(df))["Gold"]["asset_class"] == "commodity"
