"""FredClient tests -- `requests.get` is stubbed; no network."""
from __future__ import annotations

import logging
import traceback

import pytest
import requests

from peer_comparison_tool.data.clients import fred_client
from peer_comparison_tool.data.clients.fred_client import FredClient
from peer_comparison_tool.data.clients.yfinance_client import DataRetrievalError

KEY = "abcd1234secretkey5678abcd1234ef"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def _client(**kw) -> FredClient:
    return FredClient(api_key=KEY, backoff_seconds=0, **kw)


def _stub_get(monkeypatch, responses):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params})
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(fred_client.requests, "get", fake_get)
    return calls


def _full_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def test_missing_key_raises_runtime_error_without_calling_network(monkeypatch):
    calls = _stub_get(monkeypatch, [FakeResponse()])
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        FredClient(api_key=None).fetch_series_observations("DGS10")
    assert calls == []


def test_parses_sorts_and_drops_missing_markers(monkeypatch):
    payload = {"observations": [
        {"date": "2026-10-09", "value": "4.10"},
        {"date": "2026-10-08", "value": "."},
        {"date": "2026-10-07", "value": "4.05"},
    ]}
    calls = _stub_get(monkeypatch, [FakeResponse(payload=payload)])
    df = _client().fetch_series_observations("DGS10", limit=520)
    assert list(df["value"]) == [4.05, 4.10]
    assert [str(d) for d in df["date"]] == ["2026-10-07", "2026-10-09"]
    assert calls[0]["params"]["series_id"] == "DGS10"
    assert calls[0]["params"]["limit"] == 520
    assert calls[0]["params"]["sort_order"] == "desc"


def test_empty_observations_returns_empty_frame(monkeypatch):
    _stub_get(monkeypatch, [FakeResponse(payload={"observations": []})])
    df = _client().fetch_series_observations("DGS10")
    assert df.empty and list(df.columns) == ["date", "value"]


def test_client_error_is_not_retried_and_reports_fred_message(monkeypatch):
    """A 400 (bad key / bad series id) can't succeed on retry, and FRED's own
    reason must reach the user so a bad key is obvious."""
    body = {"error_code": 400, "error_message": "Bad Request. The series does not exist."}
    calls = _stub_get(monkeypatch, [FakeResponse(400, body)])
    with pytest.raises(DataRetrievalError) as exc_info:
        _client(retries=3).fetch_series_observations("NOPE")
    assert len(calls) == 1
    assert "400" in str(exc_info.value) and "series does not exist" in str(exc_info.value)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_are_retried(monkeypatch, status):
    calls = _stub_get(monkeypatch, [FakeResponse(status, {"error_message": "later"})])
    with pytest.raises(DataRetrievalError):
        _client(retries=3).fetch_series_observations("DGS10")
    assert len(calls) == 3


def test_recovers_after_a_transient_failure(monkeypatch):
    ok = FakeResponse(payload={"observations": [{"date": "2026-10-09", "value": "4.1"}]})
    calls = _stub_get(monkeypatch, [FakeResponse(503), ok])
    df = _client(retries=3).fetch_series_observations("DGS10")
    assert len(calls) == 2 and len(df) == 1


def test_api_key_never_appears_in_exception_log_or_traceback(monkeypatch, caplog):
    """Security: `requests` puts the full URL -- `api_key=...` included -- in
    its exception messages; those used to be logged and chained into the
    traceback you'd paste into a bug report."""
    leaky = requests.exceptions.HTTPError(
        "400 Client Error: Bad Request for url: https://api.stlouisfed.org/fred/series/observations"
        f"?series_id=DGS10&api_key={KEY}&file_type=json")
    leaky_conn = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='api.stlouisfed.org'): Max retries exceeded with url: "
        f"/fred/series/observations?series_id=DGS10&api_key={KEY}&file_type=json")
    for failure in (leaky, leaky_conn):
        _stub_get(monkeypatch, [failure])
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(DataRetrievalError) as exc_info:
                _client(retries=2).fetch_series_observations("DGS10")
        assert KEY not in str(exc_info.value)
        assert KEY not in _full_text(exc_info.value)
        assert KEY not in caplog.text
