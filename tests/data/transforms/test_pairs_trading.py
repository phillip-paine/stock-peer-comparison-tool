"""Tests for data.transforms.pairs_trading. All synthetic pandas fixtures —
no DB, no network, matching the convention for pure transform tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.peer_comparison_tool.data.transforms.pairs_trading import (
    align_pair_prices,
    analyze_pair,
    backtest_zscore_strategy,
    compute_hedge_ratio,
    compute_pair_spread,
    evaluate_cointegration,
    screen_pairs,
)


def _dates(n: int) -> pd.Series:
    return pd.Series(pd.date_range("2024-01-01", periods=n, freq="D"))


def _cointegrated_pair(n: int = 250, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """B is a random walk; A = 2*B + mean-reverting noise, so A and B share
    a common stochastic trend (cointegrated) with hedge ratio ~2."""
    rng = np.random.default_rng(seed)
    b = 100 + np.cumsum(rng.normal(0, 1, n))

    noise = np.zeros(n)
    for i in range(1, n):
        noise[i] = 0.7 * noise[i - 1] + rng.normal(0, 0.5)
    a = 2 * b + noise

    dates = _dates(n)
    price_a = pd.DataFrame({"date": dates, "close_price": a})
    price_b = pd.DataFrame({"date": dates, "close_price": b})
    return price_a, price_b


def _independent_pair(n: int = 250, seed: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two unrelated random walks -- should not be cointegrated."""
    rng = np.random.default_rng(seed)
    a = 100 + np.cumsum(rng.normal(0, 1, n))
    b = 50 + np.cumsum(rng.normal(0, 1, n))
    dates = _dates(n)
    price_a = pd.DataFrame({"date": dates, "close_price": a})
    price_b = pd.DataFrame({"date": dates, "close_price": b})
    return price_a, price_b


def test_align_pair_prices_inner_joins_on_date():
    price_a = pd.DataFrame({"date": _dates(5), "close_price": [1, 2, 3, 4, 5]})
    price_b = pd.DataFrame({"date": _dates(5)[1:], "close_price": [10, 20, 30, 40]})

    merged = align_pair_prices(price_a, price_b, "A", "B")

    assert len(merged) == 4
    assert set(merged.columns) == {"date", "close_price_A", "close_price_B"}


def test_compute_hedge_ratio_recovers_known_beta():
    rng = np.random.default_rng(42)
    b = 100 + np.cumsum(rng.normal(0, 1, 200))
    a = 3.0 * b + 5.0

    beta = compute_hedge_ratio(pd.Series(a), pd.Series(b))

    assert beta == pytest.approx(3.0, abs=0.01)


def test_compute_pair_spread_adds_expected_columns():
    price_a, price_b = _cointegrated_pair()
    merged = align_pair_prices(price_a, price_b, "A", "B")

    result = compute_pair_spread(merged, "close_price_A", "close_price_B")

    assert {"hedge_ratio", "spread", "zscore"}.issubset(result.columns)
    # z-score of a full series against its own mean/std should itself have
    # ~zero mean and ~unit std.
    assert result["zscore"].mean() == pytest.approx(0.0, abs=1e-6)
    assert result["zscore"].std() == pytest.approx(1.0, abs=1e-6)


def test_cointegrated_pair_is_detected():
    price_a, price_b = _cointegrated_pair()
    merged = align_pair_prices(price_a, price_b, "A", "B")

    result = evaluate_cointegration(merged["close_price_A"], merged["close_price_B"])

    assert result["cointegrated"] is True
    assert result["coint_pvalue"] < 0.05


def test_independent_random_walks_are_not_cointegrated():
    price_a, price_b = _independent_pair()
    merged = align_pair_prices(price_a, price_b, "A", "B")

    result = evaluate_cointegration(merged["close_price_A"], merged["close_price_B"])

    assert result["cointegrated"] is False
    assert result["coint_pvalue"] >= 0.05


def test_backtest_counts_trades_and_pnl_on_synthetic_zscore_path():
    # Spread rises to trigger a short entry (z > entry_z), then reverts to
    # trigger the exit (|z| < exit_z) -- exactly one round-trip trade.
    dates = _dates(6)
    spread = pd.Series([0.0, 0.0, 5.0, 5.0, 0.5, 0.5])
    zscore = pd.Series([0.0, 0.0, 3.0, 3.0, 0.2, 0.2])

    result = backtest_zscore_strategy(dates, spread, zscore, entry_z=2.0, exit_z=0.5)

    assert result["n_trades"] == 1
    # Entered short at spread=5.0 (index 2), exited at spread=0.5 (index 4):
    # short pnl = -(0.5 - 5.0) = 4.5
    assert result["trade_pnls"][0] == pytest.approx(4.5)
    assert result["total_realized_pnl"] == pytest.approx(4.5)
    assert result["win_rate"] == pytest.approx(1.0)
    assert result["open_position_at_end"] is False
    assert len(result["equity_curve"]) == len(spread)


def test_backtest_reports_open_position_at_end():
    dates = _dates(3)
    spread = pd.Series([0.0, 5.0, 5.0])
    zscore = pd.Series([0.0, 3.0, 3.0])  # never reverts inside exit_z

    result = backtest_zscore_strategy(dates, spread, zscore, entry_z=2.0, exit_z=0.5)

    assert result["n_trades"] == 0
    assert result["open_position_at_end"] is True
    assert result["unrealized_pnl_at_end"] == pytest.approx(-(5.0 - 5.0))  # still at entry level


def test_analyze_pair_returns_none_below_min_observations():
    price_a = pd.DataFrame({"date": _dates(10), "close_price": range(10)})
    price_b = pd.DataFrame({"date": _dates(10), "close_price": range(10)})

    result = analyze_pair(price_a, price_b, "A", "B", min_observations=60)

    assert result is None


def test_analyze_pair_returns_full_result_for_cointegrated_pair():
    price_a, price_b = _cointegrated_pair()

    result = analyze_pair(price_a, price_b, "A", "B", min_observations=60)

    assert result is not None
    assert result["ticker_a"] == "A"
    assert result["ticker_b"] == "B"
    assert result["cointegrated"] is True
    assert "current_zscore" in result
    assert isinstance(result["spread_series"], pd.DataFrame)


def test_screen_pairs_sorts_by_pvalue_and_covers_all_combinations():
    coint_a, coint_b = _cointegrated_pair(seed=10)
    indep_a, indep_b = _independent_pair(seed=11)

    price_frames = {
        "COINT_A": coint_a, "COINT_B": coint_b,
        "INDEP_A": indep_a, "INDEP_B": indep_b,
    }

    results = screen_pairs(price_frames)

    # 4 tickers -> 6 combinations
    assert len(results) == 6
    pvalues = [r["coint_pvalue"] for r in results]
    assert pvalues == sorted(pvalues)
    # the genuinely cointegrated pair should be the strongest candidate
    top = results[0]
    assert {top["ticker_a"], top["ticker_b"]} == {"COINT_A", "COINT_B"}
