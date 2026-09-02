"""Tests for Repository.latest_cluster_membership(), added to support the
dashboard refactor's replacement for fetch_table_data(..., most_recent=True).
"""
from __future__ import annotations

from datetime import date

from src.peer_comparison_tool.data.models import ClusterMembership
from src.peer_comparison_tool.data.repository import Repository


def test_latest_cluster_membership_keeps_max_date_per_ticker(session):
    repo = Repository(session)
    repo.upsert(
        ClusterMembership,
        [
            {"ticker": "AAPL", "date": date(2024, 1, 1), "cluster_membership": "Cluster member"},
            {"ticker": "AAPL", "date": date(2024, 2, 1), "cluster_membership": "Not cluster member"},
            {"ticker": "MSFT", "date": date(2024, 1, 15), "cluster_membership": "Cluster member"},
        ],
    )
    session.commit()

    latest = repo.latest_cluster_membership()
    latest = latest.set_index("ticker")

    assert latest.loc["AAPL", "date"] == date(2024, 2, 1)
    assert latest.loc["AAPL", "cluster_membership"] == "Not cluster member"
    assert latest.loc["MSFT", "date"] == date(2024, 1, 15)
    assert len(latest) == 2


def test_latest_cluster_membership_empty_table_returns_empty_frame(session):
    repo = Repository(session)
    result = repo.latest_cluster_membership()
    assert result.empty
