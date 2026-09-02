from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from peer_comparison_tool.data.transforms.time_series import (
    aggregate_mean_by_quarter,
    aggregate_sum,
    compute_yoy_by_date,
    compute_yoy_by_quarter,
)


class TestComputeYoyByDate:
    def test_computes_correct_direction_and_magnitude(self):
        df = pd.DataFrame([
            {"ticker": "AAPL", "date": date(2025, 6, 1), "close_price": 100.0},
            {"ticker": "AAPL", "date": date(2026, 6, 1), "close_price": 120.0},
        ])
        result = compute_yoy_by_date(df, group_cols=["ticker"], date_col="date", value_cols=["close_price"])

        assert len(result) == 1
        row = result.iloc[0]
        assert pd.to_datetime(row["date"]) == pd.Timestamp("2026-06-01")
        # up 20% from 100 -> 120, not down 20% -- direction matters here
        assert row["close_price_yoy"] == pytest.approx(20.0)

    def test_drops_rows_with_no_match_one_year_prior(self):
        df = pd.DataFrame([
            {"ticker": "AAPL", "date": date(2026, 6, 1), "close_price": 120.0},
        ])
        result = compute_yoy_by_date(df, group_cols=["ticker"], date_col="date", value_cols=["close_price"])
        assert result.empty

    def test_does_not_mix_groups(self):
        df = pd.DataFrame([
            {"ticker": "AAPL", "date": date(2025, 6, 1), "close_price": 100.0},
            {"ticker": "AAPL", "date": date(2026, 6, 1), "close_price": 110.0},
            {"ticker": "MSFT", "date": date(2025, 6, 1), "close_price": 200.0},
            {"ticker": "MSFT", "date": date(2026, 6, 1), "close_price": 300.0},
        ])
        result = compute_yoy_by_date(df, group_cols=["ticker"], date_col="date", value_cols=["close_price"])
        assert len(result) == 2
        aapl_yoy = result.loc[result["ticker"] == "AAPL", "close_price_yoy"].iloc[0]
        msft_yoy = result.loc[result["ticker"] == "MSFT", "close_price_yoy"].iloc[0]
        assert aapl_yoy == pytest.approx(10.0)
        assert msft_yoy == pytest.approx(50.0)

    def test_zero_prior_value_yields_zero_not_inf(self):
        df = pd.DataFrame([
            {"ticker": "AAPL", "date": date(2025, 6, 1), "close_price": 0.0},
            {"ticker": "AAPL", "date": date(2026, 6, 1), "close_price": 120.0},
        ])
        result = compute_yoy_by_date(df, group_cols=["ticker"], date_col="date", value_cols=["close_price"])
        assert result.iloc[0]["close_price_yoy"] == 0.0

    def test_empty_input_returns_empty_with_expected_columns(self):
        df = pd.DataFrame(columns=["ticker", "date", "close_price"])
        result = compute_yoy_by_date(df, group_cols=["ticker"], date_col="date", value_cols=["close_price"])
        assert result.empty
        assert list(result.columns) == ["ticker", "date", "close_price_yoy"]

    def test_multiple_value_columns(self):
        df = pd.DataFrame([
            {"ticker": "AAPL", "date": date(2025, 6, 1), "close_price": 100.0, "close_price_indexed": 100.0},
            {"ticker": "AAPL", "date": date(2026, 6, 1), "close_price": 150.0, "close_price_indexed": 200.0},
        ])
        result = compute_yoy_by_date(
            df, group_cols=["ticker"], date_col="date", value_cols=["close_price", "close_price_indexed"]
        )
        row = result.iloc[0]
        assert row["close_price_yoy"] == pytest.approx(50.0)
        assert row["close_price_indexed_yoy"] == pytest.approx(100.0)


class TestComputeYoyByQuarter:
    def test_matches_same_quarter_prior_year(self):
        df = pd.DataFrame([
            {"ticker": "AAPL", "date": date(2025, 3, 15), "quarter_reporting": "2025_1", "basic_eps": 1.0},
            {"ticker": "AAPL", "date": date(2026, 3, 20), "quarter_reporting": "2026_1", "basic_eps": 1.5},
        ])
        result = compute_yoy_by_quarter(
            df, group_cols=["ticker"], quarter_col="quarter_reporting", date_col="date", value_cols=["basic_eps"],
        )
        assert len(result) == 1
        assert result.iloc[0]["quarter_reporting"] == "2026_1"
        assert result.iloc[0]["basic_eps_yoy"] == pytest.approx(50.0)

    def test_does_not_match_different_quarter_number(self):
        df = pd.DataFrame([
            {"ticker": "AAPL", "date": date(2025, 6, 15), "quarter_reporting": "2025_2", "basic_eps": 1.0},
            {"ticker": "AAPL", "date": date(2026, 3, 20), "quarter_reporting": "2026_1", "basic_eps": 1.5},
        ])
        result = compute_yoy_by_quarter(
            df, group_cols=["ticker"], quarter_col="quarter_reporting", date_col="date", value_cols=["basic_eps"],
        )
        assert result.empty

    def test_empty_input_returns_empty_with_expected_columns(self):
        df = pd.DataFrame(columns=["ticker", "date", "quarter_reporting", "basic_eps"])
        result = compute_yoy_by_quarter(
            df, group_cols=["ticker"], quarter_col="quarter_reporting", date_col="date", value_cols=["basic_eps"],
        )
        assert result.empty
        assert list(result.columns) == ["ticker", "date", "quarter_reporting", "basic_eps_yoy"]


class TestAggregateSum:
    def test_sums_within_group(self):
        df = pd.DataFrame([
            {"sub_industry": "Tech Hardware", "date": date(2026, 1, 1), "close_price": 100.0},
            {"sub_industry": "Tech Hardware", "date": date(2026, 1, 1), "close_price": 50.0},
            {"sub_industry": "Banks", "date": date(2026, 1, 1), "close_price": 30.0},
        ])
        result = aggregate_sum(df, group_cols=["sub_industry", "date"], value_cols=["close_price"])
        tech_total = result.loc[result["sub_industry"] == "Tech Hardware", "close_price"].iloc[0]
        assert tech_total == pytest.approx(150.0)

    def test_empty_input(self):
        df = pd.DataFrame(columns=["sub_industry", "date", "close_price"])
        result = aggregate_sum(df, group_cols=["sub_industry", "date"], value_cols=["close_price"])
        assert result.empty


class TestAggregateMeanByQuarter:
    def test_averages_and_takes_earliest_date(self):
        df = pd.DataFrame([
            {"sub_industry": "Tech Hardware", "date": date(2026, 3, 15), "quarter_reporting": "2026_1", "basic_eps": 1.0},
            {"sub_industry": "Tech Hardware", "date": date(2026, 3, 10), "quarter_reporting": "2026_1", "basic_eps": 3.0},
        ])
        result = aggregate_mean_by_quarter(
            df, group_cols=["sub_industry"], quarter_col="quarter_reporting", date_col="date", value_cols=["basic_eps"],
        )
        assert len(result) == 1
        assert result.iloc[0]["basic_eps"] == pytest.approx(2.0)
        assert result.iloc[0]["date"] == date(2026, 3, 10)
