"""
Peer valuation dispersion screener -- pure, DB-free.

The gap this fills: `pairs_trading.py` finds relative value *between two
named tickers over time*; `dcf.py` finds absolute intrinsic value *for one
ticker at a time*; `bad_news_screener.py` is event/sentiment-driven. None
of them answer the most natural question this tool's whole premise (peer
comparison) sets up: "which of the tickers I track looks statistically
cheap or expensive *right now*, relative to its actual peers?" -- today
that's answered by eyeballing the comparison page's scatter chart one
sub-industry at a time. This makes it a systematic screen instead.

Approach: for each valuation metric (P/E, EV/EBITDA, P/B), z-score every
ticker against the mean/std of its own peer group (GICS sub-industry by
default, or the DBSCAN cluster label once `cluster_table` is populated --
either works, see `group_col`). A large negative z-score means "priced
well below its peers on this metric."

Cheap alone isn't a useful signal on its own -- it's the classic value-trap
setup (cheap for a reason: weak returns, thin margins, high leverage). So
every valuation z-score is paired with a *quality* z-score built the same
way from `return_on_equity`, `profit_margin`, and (inverted, since lower
is better) `debt_to_equity_ratio`, computed against the same peer group.
The output is one of four signals crossing valuation against quality,
rather than a single ranked "cheapest" list -- see `classify_dispersion`.

Operates on `snapshot_recent_metrics` (the frame `data_loader.py` already
builds once at dashboard startup from `TickerMostRecentMetric` + company
info + cluster label) -- no new data or pipeline work needed.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# "Lower is better" valuation multiples. A non-positive value here (loss-making
# company, negative equity, etc.) isn't a smaller version of the same thing a
# positive value is -- it's excluded from peer stats and left unscored (NaN)
# rather than ranked as "cheap", which is what a naive z-score would do.
DEFAULT_VALUATION_METRICS = ["price_eps_ratio", "enterpriseToEbitda", "price_to_book"]

# "Higher is better" quality metrics.
DEFAULT_QUALITY_METRICS_HIGHER_BETTER = ["return_on_equity", "profit_margin"]

# "Lower is better" quality metrics (sign-flipped before scoring, so a high
# resulting z-score still means "higher quality" like the others).
DEFAULT_QUALITY_METRICS_LOWER_BETTER = ["debt_to_equity_ratio"]

CHEAP_QUALITY_INTACT = "cheap_quality_intact"
CHEAP_QUALITY_WEAK = "cheap_quality_weak"
EXPENSIVE_QUALITY_STRONG = "expensive_quality_strong"
EXPENSIVE_QUALITY_WEAK = "expensive_quality_weak"
NO_SIGNAL = "no_signal"

SIGNAL_DESCRIPTIONS = {
    CHEAP_QUALITY_INTACT: "Trading below peers on valuation, without the weaker returns/margins/leverage "
                           "that would usually explain it -- worth a closer look.",
    CHEAP_QUALITY_WEAK: "Trading below peers on valuation, but returns/margins/leverage are also weaker "
                         "than peers -- possible value trap, check why it's cheap before assuming mispricing.",
    EXPENSIVE_QUALITY_STRONG: "Trading above peers on valuation, backed by stronger returns/margins/leverage "
                               "than peers -- may be fairly priced for quality, or a name to watch for a pullback.",
    EXPENSIVE_QUALITY_WEAK: "Trading above peers on valuation without stronger returns/margins/leverage to "
                             "back it up -- possible overvaluation candidate.",
}


def _zscore_within_group(
    series: pd.Series, group: pd.Series, min_group_size: int, higher_is_better_positive_only: bool = False
) -> tuple[pd.Series, pd.Series]:
    """Z-score `series` against the mean/std of its own `group`, returning
    `(zscore, peer_group_size)` aligned to `series`'s index.

    Non-positive values are excluded from a group's mean/std/size *and*
    left as NaN in the output when `higher_is_better_positive_only` is
    True (used for valuation multiples -- see module docstring on why a
    negative P/E isn't a smaller version of a positive one). Groups with
    fewer than `min_group_size` valid peers are left entirely unscored --
    a z-score against 2-3 peers is mostly noise.
    """
    values = series.copy()
    if higher_is_better_positive_only:
        values = values.where(values > 0)

    valid = values.notna()
    group_stats = (
        pd.DataFrame({"value": values[valid], "group": group[valid]})
        .groupby("group")["value"]
        .agg(["mean", "std", "count"])
    )

    zscore = pd.Series(np.nan, index=series.index)
    peer_group_size = pd.Series(0, index=series.index)

    for grp, stats in group_stats.iterrows():
        if stats["count"] < min_group_size or not stats["std"] or pd.isna(stats["std"]):
            continue
        mask = valid & (group == grp)
        zscore.loc[mask] = (values.loc[mask] - stats["mean"]) / stats["std"]
        peer_group_size.loc[mask] = int(stats["count"])

    return zscore, peer_group_size


def compute_valuation_zscores(
    snapshot_recent_metrics: pd.DataFrame,
    group_col: str = "sub_industry",
    valuation_metrics: list[str] = DEFAULT_VALUATION_METRICS,
    min_group_size: int = 4,
) -> pd.DataFrame:
    """Adds one `{metric}_zscore` column per metric in `valuation_metrics`,
    plus `valuation_zscore` (the mean of whichever of those a ticker has --
    a composite "how cheap/expensive vs peers overall" score) and
    `valuation_peer_group_size` (the smallest peer count backing any of the
    metrics that went into the composite, so a thin composite is visible,
    not hidden by averaging).
    """
    result = snapshot_recent_metrics.copy()
    zscore_cols = []
    peer_sizes = pd.DataFrame(index=result.index)

    for metric in valuation_metrics:
        if metric not in result.columns:
            continue
        col = f"{metric}_zscore"
        zscore, sizes = _zscore_within_group(
            result[metric], result[group_col], min_group_size, higher_is_better_positive_only=True
        )
        result[col] = zscore
        peer_sizes[metric] = sizes
        zscore_cols.append(col)

    result["valuation_zscore"] = result[zscore_cols].mean(axis=1) if zscore_cols else np.nan
    result["valuation_peer_group_size"] = (
        peer_sizes.replace(0, np.nan).min(axis=1).fillna(0).astype(int) if zscore_cols else 0
    )
    return result


def compute_quality_zscores(
    snapshot_recent_metrics: pd.DataFrame,
    group_col: str = "sub_industry",
    higher_better_metrics: list[str] = DEFAULT_QUALITY_METRICS_HIGHER_BETTER,
    lower_better_metrics: list[str] = DEFAULT_QUALITY_METRICS_LOWER_BETTER,
    min_group_size: int = 4,
) -> pd.DataFrame:
    """Adds one `{metric}_zscore` column per quality metric (lower-is-better
    metrics are sign-flipped so a higher resulting z-score always means
    "higher quality"), plus a composite `quality_zscore`.

    Unlike the valuation metrics, quality metrics aren't restricted to
    positive values -- a negative margin or negative ROE is a real,
    meaningfully-comparable data point (it means the company is
    unprofitable), not a different kind of thing the way a negative P/E is.
    """
    result = snapshot_recent_metrics.copy()
    zscore_cols = []

    for metric in higher_better_metrics:
        if metric not in result.columns:
            continue
        col = f"{metric}_zscore"
        zscore, _sizes = _zscore_within_group(result[metric], result[group_col], min_group_size)
        result[col] = zscore
        zscore_cols.append(col)

    for metric in lower_better_metrics:
        if metric not in result.columns:
            continue
        col = f"{metric}_zscore"
        zscore, _sizes = _zscore_within_group(-result[metric], result[group_col], min_group_size)
        result[col] = zscore
        zscore_cols.append(col)

    result["quality_zscore"] = result[zscore_cols].mean(axis=1) if zscore_cols else np.nan
    return result


def classify_dispersion(
    df: pd.DataFrame, cheap_threshold: float = -1.0, expensive_threshold: float = 1.0, quality_threshold: float = 0.0
) -> pd.DataFrame:
    """Adds a `signal` column crossing `valuation_zscore` against
    `quality_zscore` (both must already exist -- see
    `compute_valuation_zscores`/`compute_quality_zscores`).

    A ticker only gets a signal if its valuation z-score clears
    `cheap_threshold` or `expensive_threshold` *and* it has a quality
    z-score to cross it against; everything else (including any ticker
    whose peer group was too small to score at all) is `NO_SIGNAL`.
    """
    result = df.copy()
    valuation = result["valuation_zscore"]
    quality = result["quality_zscore"]

    cheap = valuation <= cheap_threshold
    expensive = valuation >= expensive_threshold
    quality_ok = quality >= quality_threshold
    has_quality_score = quality.notna()

    result["signal"] = NO_SIGNAL
    result.loc[cheap & has_quality_score & quality_ok, "signal"] = CHEAP_QUALITY_INTACT
    result.loc[cheap & has_quality_score & ~quality_ok, "signal"] = CHEAP_QUALITY_WEAK
    result.loc[expensive & has_quality_score & quality_ok, "signal"] = EXPENSIVE_QUALITY_STRONG
    result.loc[expensive & has_quality_score & ~quality_ok, "signal"] = EXPENSIVE_QUALITY_WEAK
    return result


def screen_valuation_dispersion(
    snapshot_recent_metrics: pd.DataFrame,
    group_col: str = "sub_industry",
    valuation_metrics: list[str] = DEFAULT_VALUATION_METRICS,
    higher_better_quality_metrics: list[str] = DEFAULT_QUALITY_METRICS_HIGHER_BETTER,
    lower_better_quality_metrics: list[str] = DEFAULT_QUALITY_METRICS_LOWER_BETTER,
    min_group_size: int = 4,
    cheap_threshold: float = -1.0,
    expensive_threshold: float = 1.0,
    quality_threshold: float = 0.0,
) -> list[dict[str, Any]]:
    """Full pipeline: z-score valuation and quality within peer groups,
    classify, and return every ticker with a real signal (`NO_SIGNAL`
    tickers are dropped) as a list of dicts, sorted by `|valuation_zscore|`
    descending -- the most statistically extreme names first, regardless
    of which of the four signal buckets they landed in.
    """
    if snapshot_recent_metrics.empty or group_col not in snapshot_recent_metrics.columns:
        return []

    scored = compute_valuation_zscores(snapshot_recent_metrics, group_col, valuation_metrics, min_group_size)
    scored = compute_quality_zscores(
        scored, group_col, higher_better_quality_metrics, lower_better_quality_metrics, min_group_size
    )
    scored = classify_dispersion(scored, cheap_threshold, expensive_threshold, quality_threshold)

    flagged = scored[scored["signal"] != NO_SIGNAL].copy()
    flagged["_sort_key"] = flagged["valuation_zscore"].abs()
    flagged = flagged.sort_values("_sort_key", ascending=False).drop(columns="_sort_key")

    return flagged.to_dict("records")
