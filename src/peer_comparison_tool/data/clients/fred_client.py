"""
Thin wrapper around the FRED (Federal Reserve Economic Data) REST API.

Same split as `yfinance_client.py`: this module only fetches and returns
raw observations, or raises `DataRetrievalError` after retries are
exhausted. No transformation, no persistence -- that's
`transforms/economic_releases.py` and `pipeline.ingest_economic_releases`.

FRED is genuinely optional. Unlike yfinance (no key needed) or Hugging
Face (already handled as an optional lazy setting -- see
`comparison_tool/constants.py`), FRED requires signing up for a free API
key at https://fred.stlouisfed.org/docs/api/api_key.html. `FredClient`
raises `RuntimeError` if no key is configured, on first use -- not at
import time, and not at `run_pipeline()` time unless a client is actually
passed in -- so nothing here forces every environment to have a FRED key
just to run the rest of the pipeline.

No `fredapi` dependency: FRED's plain REST endpoint
(`/fred/series/observations`) is a single JSON GET, not worth pulling in a
whole client library for.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

import pandas as pd
import requests

from .yfinance_client import DataRetrievalError

logger = logging.getLogger(__name__)

T = TypeVar("T")

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED's own convention for "no value reported yet for this period"
# (common for the most recent one or two observations of a series that
# reports with a lag) -- not a real 0.0, must be dropped, not summed/averaged.
_MISSING_VALUE_MARKER = "."


def _with_retry(fn: Callable[[], T], *, retries: int, backoff_seconds: float, description: str) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:  # requests surfaces a mix of connection/HTTP/JSON errors, not one common type
            last_exc = exc
            logger.warning("FRED call failed for %s (attempt %d/%d): %s", description, attempt, retries, exc)
            if attempt < retries:
                time.sleep(backoff_seconds * attempt)
    raise DataRetrievalError(f"FRED call failed for {description!r} after {retries} attempts") from last_exc


class FredClient:
    """Stateless wrapper -- safe to share one instance across a whole
    pipeline run, same as `YFinanceClient`."""

    def __init__(self, api_key: str | None = None, retries: int = 3, backoff_seconds: float = 1.0):
        self._api_key = api_key
        self._retries = retries
        self._backoff_seconds = backoff_seconds

    def _retry(self, fn: Callable[[], T], description: str) -> T:
        return _with_retry(fn, retries=self._retries, backoff_seconds=self._backoff_seconds, description=description)

    def fetch_series_observations(self, series_id: str, limit: int = 24) -> pd.DataFrame:
        """The most recent `limit` observations for `series_id`, oldest
        first: columns `date` (python `date`), `value` (float, missing
        observations dropped -- see `_MISSING_VALUE_MARKER`).

        `limit=24` (roughly two years of a monthly series) is enough for
        "latest vs. prior release" without pulling a series' entire
        multi-decade history on every pipeline run.
        """
        if not self._api_key:
            raise RuntimeError(
                "FRED_API_KEY is not set -- economic release data needs it. Sign up for a free key at "
                "https://fred.stlouisfed.org/docs/api/api_key.html and set the environment variable."
            )

        def _call() -> dict:
            response = requests.get(
                FRED_BASE_URL,
                params={
                    "series_id": series_id, "api_key": self._api_key, "file_type": "json",
                    "sort_order": "desc", "limit": limit,
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json()

        payload = self._retry(_call, f"{series_id} observations")
        observations = payload.get("observations", [])

        df = pd.DataFrame(observations)
        if df.empty:
            return pd.DataFrame(columns=["date", "value"])

        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["value"] = pd.to_numeric(df["value"].replace(_MISSING_VALUE_MARKER, pd.NA), errors="coerce")
        df = df.dropna(subset=["value"]).sort_values("date")
        return df[["date", "value"]].reset_index(drop=True)
