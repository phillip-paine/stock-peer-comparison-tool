from __future__ import annotations

import pandas as pd
import pytest

from peer_comparison_tool.data.clients import yfinance_client
from peer_comparison_tool.data.clients.yfinance_client import (
    DataRetrievalError,
    _ensure_field_symbol_columns,
    _with_retry,
)


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


class TestEnsureFieldSymbolColumns:
    def test_leaves_existing_multiindex_untouched(self):
        columns = pd.MultiIndex.from_product([["Close", "Open"], ["AAA", "BBB"]])
        frame = pd.DataFrame([[1, 2, 3, 4]], columns=columns)

        result = _ensure_field_symbol_columns(frame, ["AAA", "BBB"])

        assert result is frame

    def test_promotes_flat_columns_to_field_symbol_multiindex(self):
        flat = pd.DataFrame({"Close": [1.0, 2.0], "Open": [0.5, 1.5]})

        result = _ensure_field_symbol_columns(flat, ["AAA"])

        assert isinstance(result.columns, pd.MultiIndex)
        assert set(result.columns) == {("Close", "AAA"), ("Open", "AAA")}
        assert list(result[("Close", "AAA")]) == [1.0, 2.0]


class TestFetchMultiSymbolHistory:
    def _make_multiindex_frame(self, symbols, n_rows=3):
        columns = pd.MultiIndex.from_product([["Close"], symbols])
        return pd.DataFrame(
            [[float(i)] * len(symbols) for i in range(n_rows)], columns=columns
        )

    def test_splits_into_chunks_of_requested_size(self, monkeypatch):
        calls = []

        def fake_download(symbols, period, interval):
            calls.append(list(symbols))
            return self._make_multiindex_frame(symbols)

        monkeypatch.setattr(yfinance_client.yf, "download", fake_download)
        monkeypatch.setattr(yfinance_client.time, "sleep", lambda _seconds: None)

        client = yfinance_client.YFinanceClient(retries=1)
        symbols = ["A", "B", "C", "D", "E", "F", "G"]
        client.fetch_multi_symbol_history(symbols, chunk_size=3, chunk_delay_seconds=0)

        assert calls == [["A", "B", "C"], ["D", "E", "F"], ["G"]]

    def test_sleeps_between_chunks_but_not_after_the_last(self, monkeypatch):
        sleep_calls = []
        monkeypatch.setattr(yfinance_client.yf, "download",
                            lambda symbols, period, interval: self._make_multiindex_frame(symbols))
        monkeypatch.setattr(yfinance_client.time, "sleep", lambda seconds: sleep_calls.append(seconds))

        client = yfinance_client.YFinanceClient(retries=1)
        client.fetch_multi_symbol_history(["A", "B", "C", "D"], chunk_size=2, chunk_delay_seconds=2.5)

        # 2 chunks -> 1 pause between them, none after the last.
        assert sleep_calls == [2.5]

    def test_single_symbol_trailing_chunk_still_concatenates_cleanly(self, monkeypatch):
        def fake_download(symbols, period, interval):
            if len(symbols) == 1:
                return pd.DataFrame({"Close": [1.0, 2.0]})  # flat columns, as yfinance really returns
            return self._make_multiindex_frame(symbols)

        monkeypatch.setattr(yfinance_client.yf, "download", fake_download)
        monkeypatch.setattr(yfinance_client.time, "sleep", lambda _seconds: None)

        client = yfinance_client.YFinanceClient(retries=1)
        result = client.fetch_multi_symbol_history(["A", "B", "C"], chunk_size=2, chunk_delay_seconds=0)

        assert isinstance(result.columns, pd.MultiIndex)
        assert ("Close", "C") in result.columns

    def test_failed_chunk_is_skipped_not_fatal(self, monkeypatch):
        def fake_download(symbols, period, interval):
            if "B" in symbols:
                raise ConnectionError("rate limited")
            return self._make_multiindex_frame(symbols)

        monkeypatch.setattr(yfinance_client.yf, "download", fake_download)
        monkeypatch.setattr(yfinance_client.time, "sleep", lambda _seconds: None)

        client = yfinance_client.YFinanceClient(retries=1, backoff_seconds=0)
        result = client.fetch_multi_symbol_history(["A", "B", "C"], chunk_size=1, chunk_delay_seconds=0)

        # "B"'s chunk failed and was skipped; "A" and "C" still made it through.
        assert ("Close", "A") in result.columns
        assert ("Close", "C") in result.columns
        assert ("Close", "B") not in result.columns

    def test_raises_only_if_every_chunk_fails(self, monkeypatch):
        monkeypatch.setattr(yfinance_client.yf, "download",
                            lambda symbols, period, interval: (_ for _ in ()).throw(ConnectionError("down")))
        monkeypatch.setattr(yfinance_client.time, "sleep", lambda _seconds: None)

        client = yfinance_client.YFinanceClient(retries=1, backoff_seconds=0)
        with pytest.raises(DataRetrievalError):
            client.fetch_multi_symbol_history(["A", "B"], chunk_size=1, chunk_delay_seconds=0)