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

    def fetch_multi_asset_history(
        self, symbols: list[str], period: str = "2y", interval: str = "1d"
    ) -> pd.DataFrame:
        """Raw OHLCV daily price history for several symbols at once (used for
        commodities/indices/ETFs/FX). Returns a wide DataFrame with a
        2-level column MultiIndex: (field, symbol), e.g. ('Close', 'GC=F')."""
        return self._retry(
            lambda: yf.download(symbols, period=period, interval=interval),
            f"multi-asset history for {len(symbols)} symbols",
        )
