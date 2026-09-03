"""
Pure, DB-free pairs-trading analytics.

Replaces the exploratory logic in `comparison_tool/pairs_trading_model.py`
(kept in place for now, not deleted — see module docstring there) with
functions the dashboard can call on-demand against already-loaded price
data, instead of hitting yfinance directly.

Two things carried forward deliberately, two things changed:

- Kept: Engle-Granger cointegration testing (`statsmodels.tsa.stattools.coint`)
  as the core test — it's the right tool for a *pairs* page specifically.
  The original script's other approach (`create_cointegrated_spread_series`,
  Johansen test over a whole basket) solves a different problem — finding
  cointegrating combinations across 3+ assets jointly — and isn't a natural
  fit for "pick two tickers, see if they're a pair," so it's left alone.
- Changed: the original never actually built a tradeable spread for the
  Engle-Granger path (`test_individual_asset_pairs` only printed a
  cointegrated/not-cointegrated verdict). Here, `compute_pair_spread`
  estimates a hedge ratio via OLS (`price_a ~ price_b`) and builds the
  actual spread series + rolling z-score needed to say "is there a trade
  right now" and to run the backtest below.
- Changed: results are returned as data (dicts/DataFrames/Series), not
  printed or plotted with `plotly.express(...).show()` — the dashboard page
  handles all display.

`backtest_zscore_strategy` is a deliberately simple historical illustration:
enter when the z-score crosses `entry_z`, exit when it reverts inside
`exit_z`, no transaction costs, no slippage, no compounding. It answers
"what would this specific rule have done over this specific historical
window" — not a forecast, and not investment advice. The dashboard page
surfaces that caveat directly.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint


def align_pair_prices(
    price_a: pd.DataFrame, price_b: pd.DataFrame, ticker_a: str, ticker_b: str
) -> pd.DataFrame:
    """Inner-join two single-ticker price frames (each with `date` and
    `close_price` columns) on date, so both series only cover days both
    tickers actually traded."""
    merged = price_a[["date", "close_price"]].merge(
        price_b[["date", "close_price"]],
        on="date",
        how="inner",
        suffixes=(f"_{ticker_a}", f"_{ticker_b}"),
    )
    return merged.sort_values("date").reset_index(drop=True)


def compute_hedge_ratio(price_a: pd.Series, price_b: pd.Series) -> float:
    """OLS hedge ratio (beta) from regressing price_a on price_b:
    price_a ≈ alpha + beta * price_b. This is the number of units of B to
    hold per unit of A so that `price_a - beta * price_b` is the spread
    Engle-Granger cointegration actually tests for stationarity."""
    beta, _alpha = np.polyfit(price_b, price_a, deg=1)
    return float(beta)


def compute_pair_spread(merged: pd.DataFrame, col_a: str, col_b: str) -> pd.DataFrame:
    """Adds `hedge_ratio`, `spread`, and `zscore` columns to an aligned
    price frame. `zscore` is computed against the spread's own full-sample
    mean/std (not a rolling window) — simple and matches how the
    cointegration test itself was framed on this window."""
    result = merged.copy()
    hedge_ratio = compute_hedge_ratio(result[col_a], result[col_b])
    result["hedge_ratio"] = hedge_ratio
    result["spread"] = result[col_a] - hedge_ratio * result[col_b]
    spread_mean = result["spread"].mean()
    spread_std = result["spread"].std()
    result["zscore"] = (result["spread"] - spread_mean) / spread_std if spread_std else 0.0
    return result


def evaluate_cointegration(price_a: pd.Series, price_b: pd.Series, sig_level: float = 0.05) -> dict[str, Any]:
    """Engle-Granger cointegration test between two price series.

    Returns the test p-value, a `cointegrated` verdict at `sig_level`, and
    the simple correlation of the two raw price series (a quick sanity
    check — highly correlated but non-cointegrated pairs are a classic
    pairs-trading trap, since correlation says nothing about whether the
    *spread* reverts to a stable mean).
    """
    _stat, pvalue, _crit = coint(price_a, price_b)
    return {
        "coint_pvalue": float(pvalue),
        "cointegrated": bool(pvalue < sig_level),
        "correlation": float(price_a.corr(price_b)),
    }


def backtest_zscore_strategy(
    dates: pd.Series, spread: pd.Series, zscore: pd.Series, entry_z: float = 2.0, exit_z: float = 0.5
) -> dict[str, Any]:
    """Simple historical backtest of a z-score mean-reversion rule on the
    spread: go long the spread when zscore < -entry_z, short when
    zscore > entry_z, close when |zscore| < exit_z. One position at a time,
    no transaction costs or slippage, marked in spread units (not %).

    Returns trade count, win rate, total realized P&L, whether a position
    was still open at the end of the window (and its unrealized P&L if so),
    and a day-by-day equity curve (realized + mark-to-market) for charting.
    """
    position = 0
    entry_spread = None
    trade_pnls: list[float] = []
    equity_curve: list[float] = []
    realized_pnl = 0.0

    for spread_value, z in zip(spread, zscore):
        if position == 0:
            if z > entry_z:
                position = -1
                entry_spread = spread_value
            elif z < -entry_z:
                position = 1
                entry_spread = spread_value
        elif abs(z) < exit_z:
            pnl = position * (spread_value - entry_spread)
            trade_pnls.append(pnl)
            realized_pnl += pnl
            position = 0
            entry_spread = None

        unrealized = position * (spread_value - entry_spread) if position != 0 else 0.0
        equity_curve.append(realized_pnl + unrealized)

    open_at_end = position != 0
    unrealized_at_end = equity_curve[-1] - realized_pnl if equity_curve else 0.0
    n_trades = len(trade_pnls)
    win_rate = (sum(1 for p in trade_pnls if p > 0) / n_trades) if n_trades else None

    return {
        "n_trades": n_trades,
        "win_rate": win_rate,
        "total_realized_pnl": realized_pnl,
        "trade_pnls": trade_pnls,
        "open_position_at_end": open_at_end,
        "unrealized_pnl_at_end": unrealized_at_end,
        "equity_curve": pd.Series(equity_curve, index=dates.reset_index(drop=True)),
    }


def analyze_pair(
    price_a: pd.DataFrame,
    price_b: pd.DataFrame,
    ticker_a: str,
    ticker_b: str,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    sig_level: float = 0.05,
    min_observations: int = 60,
) -> dict[str, Any] | None:
    """Full pipeline for one candidate pair: align -> cointegration test ->
    spread/z-score -> backtest. Returns `None` if there isn't enough
    overlapping price history to test meaningfully (rather than a
    misleadingly precise p-value from a handful of points).
    """
    merged = align_pair_prices(price_a, price_b, ticker_a, ticker_b)
    if len(merged) < min_observations:
        return None

    col_a, col_b = f"close_price_{ticker_a}", f"close_price_{ticker_b}"
    coint_result = evaluate_cointegration(merged[col_a], merged[col_b], sig_level)

    spread_df = compute_pair_spread(merged, col_a, col_b)
    backtest = backtest_zscore_strategy(
        spread_df["date"], spread_df["spread"], spread_df["zscore"], entry_z, exit_z
    )

    return {
        "ticker_a": ticker_a,
        "ticker_b": ticker_b,
        "n_observations": len(merged),
        "current_zscore": float(spread_df["zscore"].iloc[-1]),
        "hedge_ratio": float(spread_df["hedge_ratio"].iloc[0]),
        "spread_series": spread_df,
        **coint_result,
        **backtest,
    }


def screen_pairs(
    price_frames: dict[str, pd.DataFrame],
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    sig_level: float = 0.05,
) -> list[dict[str, Any]]:
    """Run `analyze_pair` over every combination of tickers in
    `price_frames` (each value a DataFrame with `date`/`close_price` for
    one ticker). Returns a list of result dicts, sorted by cointegration
    p-value ascending (strongest candidates first) — skipped pairs (not
    enough overlapping history) are simply omitted.
    """
    tickers = list(price_frames.keys())
    results = []
    for i, ticker_a in enumerate(tickers):
        for ticker_b in tickers[i + 1:]:
            result = analyze_pair(
                price_frames[ticker_a], price_frames[ticker_b], ticker_a, ticker_b,
                entry_z=entry_z, exit_z=exit_z, sig_level=sig_level,
            )
            if result is not None:
                results.append(result)
    results.sort(key=lambda r: r["coint_pvalue"])
    return results
