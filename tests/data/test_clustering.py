from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from peer_comparison_tool.data.clustering import DEFAULT_LABEL, create_valuation_clusters

COLS = ["price_eps_ratio", "return_on_equity"]


def _tight_group(n: int, ticker_prefix: str, base: tuple[float, float]) -> pd.DataFrame:
    """n tickers clustered tightly around `base` -- should form one DBSCAN cluster."""
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "ticker": [f"{ticker_prefix}{i}" for i in range(n)],
        "price_eps_ratio": base[0] + rng.normal(0, 0.01, n),
        "return_on_equity": base[1] + rng.normal(0, 0.01, n),
    })


class TestCreateValuationClusters:
    def test_dense_group_forms_a_cluster_while_a_true_outlier_does_not(self):
        # Min-max normalization is relative to the group's own spread, so a
        # tight group with nothing to contrast against isn't a meaningful
        # test on its own -- it needs an outlier to stretch the scale against.
        group = _tight_group(6, "T", base=(20.0, 0.15))
        outlier = pd.DataFrame({"ticker": ["OUTLIER"], "price_eps_ratio": [500.0], "return_on_equity": [10.0]})
        df = pd.concat([group, outlier], ignore_index=True)

        result = create_valuation_clusters(df, COLS, eps=0.5, min_samples=3)

        group_labels = result[result["ticker"].str.startswith("T")]["cluster_membership"]
        assert (group_labels == "Cluster member").all()
        outlier_row = result[result["ticker"] == "OUTLIER"].iloc[0]
        assert outlier_row["cluster_membership"] == DEFAULT_LABEL

    def test_ticker_missing_a_clustering_column_gets_default_label(self):
        group = _tight_group(5, "T", base=(20.0, 0.15))
        incomplete = pd.DataFrame({"ticker": ["INCOMPLETE"], "price_eps_ratio": [21.0], "return_on_equity": [np.nan]})
        df = pd.concat([group, incomplete], ignore_index=True)

        result = create_valuation_clusters(df, COLS, eps=0.5, min_samples=3)
        assert len(result) == 6  # every input ticker is represented in the output
        row = result[result["ticker"] == "INCOMPLETE"].iloc[0]
        assert row["cluster_membership"] == DEFAULT_LABEL

    def test_single_row_gets_default_label_without_erroring(self):
        df = pd.DataFrame({"ticker": ["SOLO"], "price_eps_ratio": [20.0], "return_on_equity": [0.15]})
        result = create_valuation_clusters(df, COLS, eps=0.5, min_samples=3)
        assert result.iloc[0]["cluster_membership"] == DEFAULT_LABEL

    def test_empty_input_returns_empty_with_expected_columns(self):
        result = create_valuation_clusters(pd.DataFrame(), COLS)
        assert result.empty
        assert list(result.columns) == ["ticker", "cluster_membership"]

    def test_constant_column_does_not_raise_divide_by_zero(self):
        # every row has the exact same price_eps_ratio -- max - min == 0
        df = pd.DataFrame({
            "ticker": [f"T{i}" for i in range(5)],
            "price_eps_ratio": [20.0] * 5,
            "return_on_equity": [0.1, 0.5, 0.9, 0.2, 0.6],
        })
        result = create_valuation_clusters(df, COLS, eps=0.5, min_samples=3)
        assert len(result) == 5
        assert result["cluster_membership"].notna().all()

    def test_output_covers_every_input_ticker_exactly_once(self):
        df = _tight_group(8, "T", base=(20.0, 0.15))
        result = create_valuation_clusters(df, COLS, eps=0.5, min_samples=3)
        assert sorted(result["ticker"]) == sorted(df["ticker"])
