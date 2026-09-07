"""
Pure, DB-free "bad news" price-drop screening logic.

Replaces the price-drop half of `comparison_tool/bad_news_trading_model.py`
(`find_candidate_tickers` plus the top-N-by-market-cap selection that used
to live inline in `find_bad_news_price_drops`). That module is kept in
place for now, not deleted -- see its docstring for what's being replaced
and why.

Two things changed from the original:

- Operates on the DataFrames the dashboard already loads once at startup
  (`ticker_series_data`, `snapshot_recent_metrics` -- see
  `comparison_tool/data_loader.py`), not a fresh per-ticker
  `yf.Ticker(...).history()` call. The original refetched a year of price
  history for up to 20 tickers on every run; that same price history is
  already materialized by the pipeline (`ticker_time_series`) and sitting
  in memory by the time any dashboard page runs.
- Fixed a real indexing bug in the top-N ticker selection: the original
  sorted by market cap descending and then did
  `df_tickers.loc[:20, "ticker"]` *without* resetting the index first --
  `.loc` is label-based, so after a sort this selects rows whose
  *original* (pre-sort) index label is <= 20, not the 20 largest
  companies. Replaced with an explicit reset-then-`.head(n)`.

The news-fetch and LLM-grading step (was `analyse_recent_news`) still
needs live network calls (yfinance for headlines, an LLM for the grade),
so it isn't a pure transform and doesn't belong here by the convention
established for `transforms/*.py` (DB-free, network-free, tested with
synthetic fixtures only). That step lives in
`comparison_tool/news_sentiment.py`, next to the page that calls it.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from scipy.stats import trim_mean


def select_top_by_market_cap(snapshot_recent_metrics: pd.DataFrame, top_n: int = 20) -> list[str]:
    """Tickers with the largest market cap, largest first.

    Replaces the `df_tickers.sort_values(by='market_cap', ascending=False);
    df_tickers.loc[:20, "ticker"]` pattern in the original
    `find_bad_news_price_drops` -- see module docstring for the indexing
    bug that pattern had. Rows with a missing market cap are dropped
    rather than sorted in (and potentially selected) arbitrarily.
    """
    if snapshot_recent_metrics.empty or "market_cap" not in snapshot_recent_metrics.columns:
        return []
    ranked = (
        snapshot_recent_metrics.dropna(subset=["market_cap"])
        .sort_values("market_cap", ascending=False)
        .reset_index(drop=True)
    )
    return ranked["ticker"].head(top_n).tolist()


def detect_price_drop_candidates(
    ticker_series_data: pd.DataFrame,
    tickers: list[str] | None = None,
    recent_days: int = 3,
    momentum_window: tuple[int, int] = (15, 5),
    drop_threshold: float = -0.01,
    high_percentile_threshold: float = 90.0,
) -> list[dict[str, Any]]:
    """Flags tickers whose recent price action looks like a "bad news"
    reaction, using each ticker's own price history in isolation.

    Same two rules as the original `find_candidate_tickers`, made explicit
    and independently documented rather than living inline in one
    `if`/`else` block:

    1. **Fall from a recent high**: the price was in the top
       `high_percentile_threshold`-th percentile of its own trailing
       history (trimmed-mean over the `momentum_window` days, to reduce
       sensitivity to any single spike) and the last `recent_days` days
       have since dropped below its own median.
    2. **Plain recent drop**: the average close over the last
       `recent_days` days is more than `abs(drop_threshold)` below the
       average close over the `momentum_window` days before that.

    Rule 2 only fires when rule 1 doesn't -- matching the original's
    `if`/`else` structure (a "fall from a high" is reported as that, not
    also double-counted as a plain drop).

    Operates on `ticker_series_data` (long format: `ticker`, `date`,
    `close_price` -- the frame the dashboard already holds in memory after
    startup), not a fresh yfinance call per ticker. `tickers=None` screens
    every ticker present in the frame; pass an explicit list (e.g. from
    `select_top_by_market_cap`) to restrict the universe.
    """
    momentum_start, momentum_end = momentum_window
    universe = tickers if tickers is not None else ticker_series_data["ticker"].unique().tolist()
    candidates: list[dict[str, Any]] = []

    for ticker in universe:
        prices = (
            ticker_series_data.loc[ticker_series_data["ticker"] == ticker, ["date", "close_price"]]
            .dropna()
            .sort_values("date")
        )
        close = prices["close_price"]
        if len(close) < momentum_start + recent_days:
            continue  # not enough history to evaluate the momentum window

        median_price = close.quantile(0.5)
        percentile_rank = close.rank(pct=True) * 100
        momentum_slice = percentile_rank.iloc[-momentum_start:-momentum_end]
        recent_high_percentile = (
            float(trim_mean(momentum_slice, proportiontocut=0.1)) if len(momentum_slice) else None
        )
        recent_mean = float(close.iloc[-recent_days:].mean())
        prior_mean = float(close.iloc[-momentum_start:-momentum_end].mean())
        price_drop_pct = (recent_mean / prior_mean - 1) if prior_mean else None

        fell_from_high = (
            recent_mean < median_price
            and recent_high_percentile is not None
            and recent_high_percentile > high_percentile_threshold
        )

        if fell_from_high:
            candidates.append({
                "ticker": ticker,
                "reason": "fall_from_recent_high",
                "recent_mean_price": recent_mean,
                "median_price": float(median_price),
                "recent_high_percentile": recent_high_percentile,
                "price_drop_pct": price_drop_pct,
            })
        elif price_drop_pct is not None and price_drop_pct < drop_threshold:
            candidates.append({
                "ticker": ticker,
                "reason": "recent_price_drop",
                "recent_mean_price": recent_mean,
                "median_price": float(median_price),
                "recent_high_percentile": recent_high_percentile,
                "price_drop_pct": price_drop_pct,
            })

    return candidates
