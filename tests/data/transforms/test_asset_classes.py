from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from peer_comparison_tool.data.transforms.asset_classes import transform_asset_class_series


def _multi_asset_raw(close_data: dict[str, list[float]], dates: list[str]) -> pd.DataFrame:
    """Build a raw frame shaped like yfinance's yf.download() output:
    a 2-level column MultiIndex of (field, symbol)."""
    idx = pd.to_datetime(dates)
    close_df = pd.DataFrame(close_data, index=idx)
    # yfinance always returns more than one field (Open/High/Low/Close/Volume);
    # include a second field to make sure the transform correctly selects
    # only 'Close' rather than assuming it's the only level-0 value.
    volume_df = pd.DataFrame({k: [1000] * len(idx) for k in close_data}, index=idx)
    return pd.concat({"Close": close_df, "Volume": volume_df}, axis=1)


SYMBOL_TO_NAME = {"GC=F": "GoldFutures", "SPY": "S&P500_ETF"}
NAME_TO_CLASS = {"GoldFutures": "commodity", "S&P500_ETF": "etf"}


class TestTransformAssetClassSeries:
    def test_basic_shape_and_asset_class_mapping(self):
        raw = _multi_asset_raw(
            {"GC=F": [2000.0, 2100.0], "SPY": [500.0, 510.0]},
            ["2026-01-01", "2026-01-02"],
        )
        result = transform_asset_class_series(raw, SYMBOL_TO_NAME, NAME_TO_CLASS)

        assert set(result["ticker"]) == {"GoldFutures", "S&P500_ETF"}
        gold_row = result[(result["ticker"] == "GoldFutures") & (result["date"] == date(2026, 1, 1))].iloc[0]
        assert gold_row["asset_class"] == "commodity"
        assert gold_row["close_price"] == 2000.0

    def test_indexes_to_100_at_first_date_per_symbol(self):
        raw = _multi_asset_raw(
            {"GC=F": [2000.0, 2200.0]},
            ["2026-01-01", "2026-01-02"],
        )
        result = transform_asset_class_series(raw, SYMBOL_TO_NAME, NAME_TO_CLASS)
        first = result[result["date"] == date(2026, 1, 1)].iloc[0]
        second = result[result["date"] == date(2026, 1, 2)].iloc[0]
        assert first["close_price_indexed"] == pytest.approx(100.0)
        assert second["close_price_indexed"] == pytest.approx(2200.0 / 2000.0 * 100)

    def test_computes_yoy_for_matching_prior_year_date(self):
        raw = _multi_asset_raw(
            {"GC=F": [2000.0, 2400.0]},
            ["2025-06-01", "2026-06-01"],
        )
        result = transform_asset_class_series(raw, SYMBOL_TO_NAME, NAME_TO_CLASS)
        current_year_row = result[result["date"] == date(2026, 6, 1)].iloc[0]
        assert current_year_row["close_price_yoy"] == pytest.approx(20.0)

    def test_yoy_is_nan_when_no_prior_year_data(self):
        raw = _multi_asset_raw({"GC=F": [2000.0]}, ["2026-06-01"])
        result = transform_asset_class_series(raw, SYMBOL_TO_NAME, NAME_TO_CLASS)
        assert pd.isna(result.iloc[0]["close_price_yoy"])

    def test_backfills_missing_leading_values(self):
        raw = _multi_asset_raw(
            {"GC=F": [np.nan, 2100.0, 2200.0]},
            ["2026-01-01", "2026-01-02", "2026-01-03"],
        )
        result = transform_asset_class_series(raw, SYMBOL_TO_NAME, NAME_TO_CLASS)
        first = result[result["date"] == date(2026, 1, 1)].iloc[0]
        assert first["close_price"] == pytest.approx(2100.0)

    def test_empty_input_returns_empty_with_expected_columns(self):
        result = transform_asset_class_series(pd.DataFrame(), SYMBOL_TO_NAME, NAME_TO_CLASS)
        assert result.empty
        assert list(result.columns) == [
            "ticker", "date", "asset_class", "close_price", "close_price_indexed", "close_price_yoy",
        ]
