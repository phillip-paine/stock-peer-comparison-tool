from __future__ import annotations

import pytest

from peer_comparison_tool.data.clients.yfinance_client import DataRetrievalError, _with_retry


class TestWithRetry:
    def test_returns_result_on_first_success(self):
        calls = []

        def fn():
            calls.append(1)
            return "ok"

        result = _with_retry(fn, retries=3, backoff_seconds=0, description="test")
        assert result == "ok"
        assert len(calls) == 1

    def test_retries_then_succeeds(self):
        attempts = {"count": 0}

        def fn():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ConnectionError("transient failure")
            return "recovered"

        result = _with_retry(fn, retries=5, backoff_seconds=0, description="test")
        assert result == "recovered"
        assert attempts["count"] == 3

    def test_raises_data_retrieval_error_after_exhausting_retries(self):
        def fn():
            raise ConnectionError("always fails")

        with pytest.raises(DataRetrievalError) as exc_info:
            _with_retry(fn, retries=3, backoff_seconds=0, description="AAPL info")

        assert "AAPL info" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, ConnectionError)

    def test_stops_at_exact_retry_count(self):
        attempts = {"count": 0}

        def fn():
            attempts["count"] += 1
            raise ValueError("boom")

        with pytest.raises(DataRetrievalError):
            _with_retry(fn, retries=4, backoff_seconds=0, description="test")

        assert attempts["count"] == 4
