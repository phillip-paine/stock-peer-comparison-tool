"""
Economic release latest-vs-prior comparison -- pure, DB-free.

Same shape as `report_comparison.py`'s latest-vs-prior logic (metric /
prior value / latest value / change), applied to FRED series instead of a
company's financial statements. Kept as its own module rather than reusing
`report_comparison.build_comparison_table` directly: that function expects
one wide DataFrame with a column per metric and a period-label column,
whereas each FRED series arrives as its own long, two-column
(date, value) frame from `FredClient.fetch_series_observations` -- close
enough in spirit to share the "latest two, oldest first" idea, not close
enough in shape to share the same function without forcing an awkward
reshape on one side or the other.

Starter series list, per Phillip's call to include CPI/JOLTS/payrolls/
unemployment/Fed funds first: expand `FRED_SERIES` as more are wanted --
any valid FRED series ID works, the ingestion and comparison logic here
doesn't hardcode anything about these five.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

FRED_SERIES = {
    "CPIAUCSL": "CPI (All Items)",
    "JTSJOL": "JOLTS Job Openings",
    "PAYEMS": "Nonfarm Payrolls",
    "UNRATE": "Unemployment Rate",
    "FEDFUNDS": "Effective Fed Funds Rate",
}

# Series where the value is a percentage already (unemployment rate 4.1,
# not 0.041) -- shown with a "%" suffix rather than treated as a fraction
# to multiply by 100 (that's PERCENT_METRICS's job in report_comparison.py,
# a different convention -- don't confuse the two).
PERCENT_SERIES = {"UNRATE", "FEDFUNDS"}


def latest_vs_prior_release(observations: pd.DataFrame, series_id: str) -> dict[str, Any] | None:
    """One release's latest-vs-prior comparison from `observations`
    (`date`, `value`, oldest first -- as `FredClient.fetch_series_observations`
    returns). `None` if there's no data at all for this series (e.g. a
    typo'd series ID, or FRED returning nothing).

    A series with only one observation still returns a row (`prior_value`
    `None`) rather than `None` outright -- consistent with
    `report_comparison.build_comparison_table`'s same choice for a ticker
    with thin history.
    """
    if observations.empty:
        return None

    latest = observations.iloc[-1]
    prior = observations.iloc[-2] if len(observations) > 1 else None

    latest_value = latest["value"]
    prior_value = prior["value"] if prior is not None else None

    change = None
    change_pct = None
    if prior_value is not None and pd.notna(prior_value):
        change = latest_value - prior_value
        if prior_value != 0:
            change_pct = change / abs(prior_value)

    return {
        "series_id": series_id,
        "name": FRED_SERIES.get(series_id, series_id),
        "latest_date": latest["date"],
        "latest_value": latest_value,
        "prior_date": prior["date"] if prior is not None else None,
        "prior_value": prior_value,
        "change": change,
        "change_pct": change_pct,
    }


def build_release_summary(observations_by_series: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """`latest_vs_prior_release` for every series in `observations_by_series`,
    dropping any series with no data rather than raising -- one series
    FRED couldn't return shouldn't blank the whole page.
    """
    rows = []
    for series_id, observations in observations_by_series.items():
        row = latest_vs_prior_release(observations, series_id)
        if row is not None:
            rows.append(row)
    return rows
