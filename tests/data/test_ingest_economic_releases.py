"""`pipeline.ingest_economic_releases` against the in-memory DB with a fake FRED client."""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from peer_comparison_tool.data.clients.yfinance_client import DataRetrievalError
from peer_comparison_tool.data.models import EconomicReleaseData
from peer_comparison_tool.data.pipeline import ingest_economic_releases
from peer_comparison_tool.data.repository import Repository
from peer_comparison_tool.data.transforms.economic_releases import SERIES_CATALOG


class FakeFredClient:
    def __init__(self, data=None, raise_on=None):
        self.data = data or {}
        self.raise_on = raise_on or set()
        self.calls: list[tuple[str, int]] = []

    def fetch_series_observations(self, series_id: str, limit: int = 24) -> pd.DataFrame:
        self.calls.append((series_id, limit))
        if series_id in self.raise_on:
            raise DataRetrievalError(f"boom {series_id}")
        rows = self.data.get(series_id, [(date(2026, 9, 1), 1.0), (date(2026, 10, 1), 2.0)])
        return pd.DataFrame(rows, columns=["date", "value"])


def _stored(session):
    return {(r.series_id, r.date): r.value for r in session.query(EconomicReleaseData).all()}


def test_defaults_to_full_catalog_with_per_series_history_limit(session):
    client = FakeFredClient()
    fetched = ingest_economic_releases(client, Repository(session), max_age_days=1)
    assert set(fetched) == set(SERIES_CATALOG)
    limits = dict(client.calls)
    assert limits["DGS10"] == SERIES_CATALOG["DGS10"].history_limit
    assert limits["DGS10"] > limits["CPIAUCSL"] >= 14


def test_series_outside_catalog_use_default_limit(session):
    client = FakeFredClient()
    ingest_economic_releases(client, Repository(session), series_ids=["SOMETHING_NEW"], max_age_days=1)
    assert client.calls == [("SOMETHING_NEW", 24)]


def test_persists_and_skips_recently_fetched(session):
    repo = Repository(session)
    client = FakeFredClient({"DGS10": [(date(2026, 10, 8), 4.1), (date(2026, 10, 9), 4.15)]})
    assert ingest_economic_releases(client, repo, series_ids=["DGS10"], max_age_days=1) == ["DGS10"]
    session.commit()
    assert _stored(session) == {("DGS10", date(2026, 10, 8)): 4.1, ("DGS10", date(2026, 10, 9)): 4.15}
    assert ingest_economic_releases(client, repo, series_ids=["DGS10"], max_age_days=1) == []
    assert len(client.calls) == 1


def test_revised_values_overwrite_stored_ones(session, monkeypatch):
    """Regression: written with mode="ignore", so a revision (payrolls/JOLTS
    are revised for months; FOMC projections change each meeting) never
    replaced the first-printed value."""
    repo = Repository(session)
    monkeypatch.setattr(Repository, "is_data_recent", lambda self, *a, **k: False)
    ingest_economic_releases(FakeFredClient({"PAYEMS": [(date(2026, 8, 1), 159_000.0), (date(2026, 9, 1), 159_100.0)]}),
                             repo, series_ids=["PAYEMS"])
    session.commit()
    ingest_economic_releases(FakeFredClient({"PAYEMS": [(date(2026, 8, 1), 159_040.0), (date(2026, 9, 1), 159_200.0),
                                                        (date(2026, 10, 1), 159_300.0)]}), repo, series_ids=["PAYEMS"])
    session.commit()
    assert _stored(session) == {("PAYEMS", date(2026, 8, 1)): 159_040.0, ("PAYEMS", date(2026, 9, 1)): 159_200.0,
                                ("PAYEMS", date(2026, 10, 1)): 159_300.0}


def test_failing_series_is_skipped_and_retried_next_run(session):
    repo = Repository(session)
    fetched = ingest_economic_releases(FakeFredClient(raise_on={"DGS2"}), repo,
                                       series_ids=["DGS10", "DGS2"], max_age_days=1)
    session.commit()
    assert fetched == ["DGS10"] and {sid for sid, _ in _stored(session)} == {"DGS10"}
    assert repo.is_data_recent("DGS10", 1) and not repo.is_data_recent("DGS2", 1)


def test_empty_response_is_skipped(session):
    client = FakeFredClient({"DGS10": []})
    assert ingest_economic_releases(client, Repository(session), series_ids=["DGS10"], max_age_days=1) == []


def test_every_series_failing_logs_one_clear_error_pointing_at_the_key(session, caplog):
    with caplog.at_level(logging.ERROR):
        fetched = ingest_economic_releases(FakeFredClient(raise_on=set(SERIES_CATALOG)), Repository(session),
                                           max_age_days=1)
    assert fetched == []
    assert any("FRED_API_KEY" in r.message for r in caplog.records if r.levelno >= logging.ERROR)


def test_partial_failure_does_not_log_the_all_failed_error(session, caplog):
    with caplog.at_level(logging.ERROR):
        ingest_economic_releases(FakeFredClient(raise_on={"DGS2"}), Repository(session),
                                 series_ids=["DGS10", "DGS2"], max_age_days=1)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
