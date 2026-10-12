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
import re
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


class FredRequestError(Exception):
    """A FRED request failed. The message is already scrubbed of the API key
    (see `_redact`): `requests` embeds the full request URL, `api_key=...`
    included, in its own exception messages, and those must never be logged
    or chained into a traceback that might get pasted into a bug report.

    `retryable` is False for HTTP 4xx other than 429 (a bad key or mistyped
    series ID can't be fixed by retrying), so a wrong key fails fast instead
    of burning the whole backoff schedule once per series.
    """

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


_API_KEY_IN_URL = re.compile(r"(api_key=)[^&\s'\")]+")


def _redact(text: str, api_key: str | None) -> str:
    """Remove the API key from `text`, as a literal value and as an
    `api_key=` query parameter."""
    if api_key:
        text = text.replace(api_key, "***")
    return _API_KEY_IN_URL.sub(r"\1***", text)


def _with_retry(fn: Callable[[], T], *, retries: int, backoff_seconds: float, description: str) -> T:
    last_exc: Exception | None = None
    attempts_made = 0
    for attempt in range(1, retries + 1):
        attempts_made = attempt
        try:
            return fn()
        except Exception as exc:  # requests surfaces a mix of connection/HTTP/JSON errors, not one common type
            last_exc = exc
            logger.warning("FRED call failed for %s (attempt %d/%d): %s", description, attempt, retries, exc)
            if not getattr(exc, "retryable", True):
                break
            if attempt < retries:
                time.sleep(backoff_seconds * attempt)
    attempts = f"{attempts_made} attempt{'s' if attempts_made != 1 else ''}"
    raise DataRetrievalError(f"FRED call failed for {description!r} after {attempts}: {last_exc}") from last_exc


def _fred_error_detail(response: requests.Response) -> str:
    """FRED's own explanation (`error_message` in its JSON body), e.g.
    "api_key is not registered", so a bad key is diagnosable from the log."""
    try:
        detail = response.json().get("error_message")
    except Exception:
        detail = None
    return detail or (response.text or "").strip()[:200] or "no detail returned"


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
            try:
                response = requests.get(
                    FRED_BASE_URL,
                    params={
                        "series_id": series_id, "api_key": self._api_key, "file_type": "json",
                        "sort_order": "desc", "limit": limit,
                    },
                    timeout=10,
                )
            except requests.RequestException as exc:
                # `from None`: the original message carries the request URL (and key).
                raise FredRequestError(_redact(f"{type(exc).__name__}: {exc}", self._api_key)) from None

            if response.status_code >= 400:
                detail = _redact(_fred_error_detail(response), self._api_key)
                retryable = response.status_code == 429 or response.status_code >= 500
                raise FredRequestError(f"HTTP {response.status_code}: {detail}", retryable=retryable)
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
