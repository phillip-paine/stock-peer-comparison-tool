"""
DBSCAN-based valuation clustering.

Replaces `data/utils.py`. Same algorithm and defaults as the original
(`eps=0.5`, `min_samples=3` — the values actually used at the call site in
`create_aggregations_data`, not the different defaults on the old function
signature itself, which were never used in practice). Behavior preserved
exactly:

- Tickers missing any of the clustering columns (or missing `ticker`
  itself) are excluded from the DBSCAN fit entirely, then re-attached
  afterwards with the default label — clustering can't place a point it
  has no coordinates for.
- Each column is min-max normalized to [0, 1] before fitting (with a small
  epsilon in the denominator to avoid divide-by-zero when a column is
  constant across every row in the group).
- DBSCAN's noise label (`-1`) and the "too few rows to cluster" case both
  map to the same `DEFAULT_LABEL`, same as the original — this module
  doesn't distinguish "no data", "outlier", and "not enough peers to form
  a cluster" in the output, only in how they're described here.

This is a pure function: no DB access. The orchestration that decides
*which* sub-industries to cluster, fetches their data via `Repository`, and
writes the result back lives in `aggregations.refresh_valuation_clusters()`.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

DEFAULT_LABEL = "Not cluster member"


def create_valuation_clusters(
    df: pd.DataFrame,
    cols: Sequence[str],
    eps: float = 0.5,
    min_samples: int = 3,
) -> pd.DataFrame:
    """Cluster tickers by valuation metrics. Returns a DataFrame with just
    `ticker` and `cluster_membership` (`"Cluster member"` or
    `DEFAULT_LABEL`), covering every ticker in the input — including ones
    dropped from the fit for missing data.
    """
    if df.empty:
        return pd.DataFrame(columns=["ticker", "cluster_membership"])

    fittable = df.dropna(subset=["ticker", *cols], how="any").copy()
    fittable = _apply_dbscan(fittable, cols, eps, min_samples)

    result = df[["ticker"]].merge(fittable[["ticker", "label"]], on="ticker", how="left")
    result["cluster_membership"] = result["label"].fillna(DEFAULT_LABEL)
    return result[["ticker", "cluster_membership"]]


def _apply_dbscan(df: pd.DataFrame, cols: Sequence[str], eps: float, min_samples: int) -> pd.DataFrame:
    if len(df.index) <= 1:
        # DBSCAN needs at least a couple of points to find neighborhoods;
        # a single ticker can't be "clustered" against anything.
        df = df.copy()
        df["label"] = DEFAULT_LABEL
        return df

    normalized_columns = []
    for col in cols:
        col_min, col_max = df[col].min(), df[col].max()
        normalized_columns.append((df[col].values - col_min) / (col_max - col_min + 0.0001))

    df = df.copy()
    df["cluster"] = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(X=np.column_stack(normalized_columns))
    df["label"] = np.where(df["cluster"] != -1, "Cluster member", DEFAULT_LABEL)
    return df
