"""
Thin wrapper around the yfinance library.

Replaces the fetch side of `data/retriever.py`. Every method here does
exactly one thing: call yfinance and return whatever it gives back (or raise
`DataRetrievalError` after retries are exhausted). No column renaming,
no derived metrics, no persistence — that all lives in `transforms/`, which
can be tested without a network call. This split is the main structural
change from the original `RetrieveStockData`/`RetrieveEconomicsData`, which
each fetched data *and* computed margins/ratios/YoY *and* shaped it for
storage, all in the same class, with fetches triggered as a side effect of
`__init__`.

Retry/backoff is new: the original had no protection against yfinance's
rate limiting, so a transient failure partway through a run would abort
that ticker outright.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DataRetrievalError(Exception):
    """Raised when a yfinance call fails after all retries are exhausted."""


def _with_retry(fn: Callable[[], T], *, retries: int, backoff_seconds: float, description: str) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:  # yfinance surfaces a mix of requests/JSON/HTTP errors, not one common type
            last_exc = exc
            logger.warning("yfinance call failed for %s (attempt %d/%d): %s", description, attempt, retries, exc)
            if attempt < retries:
                time.sleep(backoff_seconds * attempt)
    raise DataRetrievalError(f"yfinance call failed for {description!r} after {retries} attempts") from last_exc


def _ensure_field_symbol_columns(frame: pd.DataFrame, chunk: list[str]) -> pd.DataFrame:
    """`yf.download()` returns a 2-level (field, symbol) column MultiIndex
    for a multi-symbol chunk, but flat (field-only) columns for a
    single-symbol chunk — which happens routinely here since chunking can
    leave a lone straggler as the last chunk. Normalize both shapes to the
    same 2-level MultiIndex so chunks concatenate back together safely
    regardless of chunk size."""
    if isinstance(frame.columns, pd.MultiIndex):
        return frame
    return pd.concat({chunk[0]: frame}, axis=1).swaplevel(0, 1, axis=1)


class YFinanceClient:
    """Stateless wrapper — safe to share one instance across a whole pipeline run."""

    def __init__(self, retries: int = 3, backoff_seconds: float = 1.0):
        self._retries = retries
        self._backoff_seconds = backoff_seconds

    def _retry(self, fn: Callable[[], T], description: str) -> T:
        return _with_retry(fn, retries=self._retries, backoff_seconds=self._backoff_seconds, description=description)

    def fetch_info(self, ticker: str) -> dict:
        """Raw `Ticker.info` dict: sector, industry, market cap, valuation ratios, etc."""
        stock = yf.Ticker(ticker)
        return self._retry(lambda: stock.info, f"{ticker} info")

    def fetch_quarterly_financials(self, ticker: str) -> pd.DataFrame:
        """Raw quarterly income statement: rows are line items, columns are report dates."""
        stock = yf.Ticker(ticker)
        return self._retry(lambda: stock.quarterly_financials, f"{ticker} quarterly financials")

    def fetch_balance_sheet(self, ticker: str) -> pd.DataFrame:
        """Raw annual balance sheet: rows are line items, columns are report dates."""
        stock = yf.Ticker(ticker)
        return self._retry(lambda: stock.get_balance_sheet(), f"{ticker} balance sheet")

    def fetch_cashflow(self, ticker: str) -> pd.DataFrame:
        """Raw cashflow statement: rows are line items, columns are report dates."""
        stock = yf.Ticker(ticker)
        return self._retry(lambda: stock.cashflow, f"{ticker} cashflow")

    def fetch_price_history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        """Raw OHLCV daily price history for one ticker."""
        stock = yf.Ticker(ticker)
        return self._retry(lambda: stock.history(period=period), f"{ticker} price history")

    def fetch_multi_symbol_history(
            self,
            symbols: list[str],
            period: str = "2y",
            interval: str = "1d",
            chunk_size: int = 5,
            chunk_delay_seconds: float = 2.0,
    ) -> pd.DataFrame:
        """Raw OHLCV daily price history for several symbols at once — used
        for both the asset-class universe (indices/ETFs/commodities/FX) and,
        now, stock tickers. Returns a wide DataFrame with a 2-level column
        MultiIndex: (field, symbol), e.g. ('Close', 'GC=F').

        Looping `fetch_price_history(ticker)` one ticker at a time is
        exactly the pattern that triggers Yahoo's rate limiter almost
        immediately — `yf.download()` natively supports fetching many
        symbols in far fewer HTTP requests than one-by-one `Ticker.history()`
        calls. Fetched in chunks of `chunk_size` symbols, with a pause
        between chunks, rather than one call covering every symbol at once
        — a single call for the whole asset-class universe (17 symbols) has
        on its own triggered Yahoo's rate limiter for the *entire* batch
        together, and the retry backoff in `_retry` is tuned for transient
        failures, not rate-limit cooldowns. A chunk that still fails after
        its own retries is skipped (logged, not raised) rather than
        discarding every other chunk's data — this method only raises if
        every chunk failed.
        """
        chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]
        frames = []
        for i, chunk in enumerate(chunks):
            try:
                frame = self._retry(
                    lambda chunk=chunk: yf.download(chunk, period=period, interval=interval),
                    f"multi-symbol history chunk {i + 1}/{len(chunks)} ({chunk})",
                )
            except DataRetrievalError as exc:
                logger.warning("Skipping multi-symbol history chunk %d/%d %s: %s", i + 1, len(chunks), chunk, exc)
                continue
            frames.append(_ensure_field_symbol_columns(frame, chunk))
            if i < len(chunks) - 1:
                time.sleep(chunk_delay_seconds)

        if not frames:
            raise DataRetrievalError(
                f"All {len(chunks)} chunk(s) failed for multi-symbol history ({len(symbols)} symbols)"
            )
        return pd.concat(frames, axis=1)