"""Price tools: single-instrument history and the cross-asset 'what moved' table."""
from __future__ import annotations

from typing import Any

import pandas as pd

from ...data.constants import ASSET_CLASS_TICKERS, asset_name_to_class, asset_symbol_to_name
from ...data.models import AssetClassTimeSeries, TickerTimeSeries
from ...data.transforms.market_conditions import compute_asset_moves
from ..errors import ToolInputError
from ..read_repository import ReadRepository
from ..serialize import clamp, df_records, to_jsonable
from .reference import unknown_ticker_message

DEFAULT_OBSERVATIONS = 120
MAX_OBSERVATIONS = 750
# Period used to keep the LAST ACTUAL trading day of each week/month (so a row's
# date is a real observation date, never a calendar period end with no trade).
_PERIOD_BY_FREQUENCY = {"weekly": "W-FRI", "monthly": "M"}
FREQUENCIES = ("daily", *_PERIOD_BY_FREQUENCY)

_RATE_NOTE = (
    "Treasury yield series are quoted in percentage points (4.25 means 4.25%), not as a price."
)


def _find_asset_name(raw: str) -> str | None:
    """Map a yfinance symbol ('SPY', '^TNX') or friendly name ('US10Y_Yield'),
    case-insensitively, to the name asset series are stored under."""
    wanted = raw.strip().casefold()
    symbol_to_name = asset_symbol_to_name()
    for symbol, name in symbol_to_name.items():
        if wanted in (symbol.casefold(), name.casefold()):
            return name
    return None


def price_history(
    repo: ReadRepository,
    ticker: str,
    observations: int = DEFAULT_OBSERVATIONS,
    frequency: str = "daily",
) -> dict[str, Any]:
    """Close-price history for a stock ticker OR a tracked asset (index, ETF,
    commodity future, FX pair, Treasury yield), most recent `observations` rows."""
    if frequency not in FREQUENCIES:
        raise ToolInputError(f"frequency must be one of {', '.join(FREQUENCIES)} (got {frequency!r}).")
    observations = clamp(observations, 1, MAX_OBSERVATIONS)

    raw = (ticker or "").strip()
    if not raw:
        raise ToolInputError("ticker is required.")

    symbol = raw.upper()
    series = repo.fetch_dataframe(TickerTimeSeries, ticker=symbol)
    source, instrument, asset_class = "stock", symbol, None
    if series.empty:
        name = _find_asset_name(raw)
        if name is not None:
            series = repo.fetch_dataframe(AssetClassTimeSeries, ticker=name)
            source, instrument, asset_class = "asset_class", name, asset_name_to_class().get(name)
        if series.empty:
            known_assets = ", ".join(sorted(asset_symbol_to_name().values()))
            raise ToolInputError(
                f"No price history for {raw!r}. {unknown_ticker_message(repo, symbol)} "
                f"Tracked non-stock series: {known_assets}."
            )

    df = series.assign(date=pd.to_datetime(series["date"])).sort_values("date")
    df = df.dropna(subset=["close_price"])
    if df.empty:
        raise ToolInputError(f"{instrument} has rows stored but no non-null closing prices.")
    if frequency != "daily":
        df = df.groupby(df["date"].dt.to_period(_PERIOD_BY_FREQUENCY[frequency])).tail(1)
    df = df.tail(observations)

    first, last = df.iloc[0], df.iloc[-1]
    period_return = None
    if first["close_price"]:
        period_return = last["close_price"] / first["close_price"] - 1

    notes = []
    if source == "stock":
        notes.append(
            "close_indexed is the close rebased to 100 at the first date of the stored window "
            "(not at the first row returned here); use 'close' for levels."
        )
    if asset_class == "rate":
        notes.append(_RATE_NOTE)

    return to_jsonable({
        "instrument": instrument,
        "source": source,
        "asset_class": asset_class,
        "frequency": frequency,
        "as_of": last["date"],
        "summary": {
            "first_date": first["date"],
            "last_date": last["date"],
            "first_close": first["close_price"],
            "last_close": last["close_price"],
            "period_return": period_return,      # fraction: 0.05 = +5%
            "high_close": df["close_price"].max(),
            "low_close": df["close_price"].min(),
        },
        "observations": int(len(df)),
        "rows": df_records(
            df.rename(columns={"close_price": "close", "close_price_indexed": "close_indexed"}).round(4),
            ["date", "close", "close_indexed"],
        ),
        "notes": notes,
    })


def asset_moves(repo: ReadRepository, asset_class: str | None = None) -> dict[str, Any]:
    """Latest level and 1-day / 1-week / 1-month change for every tracked
    non-stock asset: commodities, indices, ETFs, FX and Treasury yields."""
    known = list(ASSET_CLASS_TICKERS)
    if asset_class is not None and asset_class.strip().casefold() not in known:
        raise ToolInputError(f"asset_class must be one of {', '.join(known)} (got {asset_class!r}).")

    df = repo.fetch_dataframe(AssetClassTimeSeries)
    rows = compute_asset_moves(df)
    name_to_symbol = {name: symbol for symbol, name in asset_symbol_to_name().items()}
    for row in rows:
        row["symbol"] = name_to_symbol.get(row["ticker"])
    if asset_class is not None:
        wanted = asset_class.strip().casefold()
        rows = [r for r in rows if str(r["asset_class"]).casefold() == wanted]
    rows.sort(key=lambda r: (str(r["asset_class"]), str(r["ticker"])))

    return to_jsonable({
        "count": len(rows),
        "assets": rows,
        "notes": [
            "change_1d / 1w / 1m are fractions (0.012 = +1.2%) over 1 / 5 / 21 trading days; "
            "null where there isn't enough history.",
            "For the 'rate' class, latest_price is a yield in percentage points and the change is "
            "the relative change of that yield, not basis points.",
        ],
    })
