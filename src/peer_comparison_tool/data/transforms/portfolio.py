"""
Portfolio maths -- pure, DB-free.

Everything the portfolio page shows is computed here from plain DataFrames,
so the Dash page stays thin and every rule below is unit-tested.

Conventions
-----------
* **Reporting currency is USD.** Each lot carries its own currency, the FX
  rate (USD per 1 unit of that currency) at purchase, and the current rate.
  USD cost basis = shares x purchase price x *purchase-date* FX, so unrealised
  USD P&L includes the currency move since purchase; USD market value uses the
  *current* rate.
* **Current FX** is the pipeline's series (`CADUSD_fx`) unless a manual rate
  is at least as recent, in which case the manual one wins (ties go to
  manual). See `resolve_current_fx`.
* **Manually priced positions** (e.g. CAD-hedged funds the pipeline can't
  see) are priced from hand-entered marks. Between marks the price is held
  flat, and before the first mark it is the purchase price. History, return
  and risk stats treat them that way -- which understates their volatility
  and correlation, and the page says so.
* **Return** is time-weighted (chain-linked daily returns of the positions
  held at the previous close, in USD), so buying more shares doesn't register
  as performance. A lot's first priced day is its purchase date at cost; its
  first return is the following day.
* **Dividends are entered by hand** as cash received on a pay date (total
  amount, in the holding's currency, converted at that date's FX). They are
  income, not reinvested: they add to total value and total return, and the
  time-weighted return counts them on the pay date (spread over the lots of
  that ticker held at the prior close, by shares). The stats panel also shows
  the price-only return so the two can be compared.
* Stats that need history (annualised return, volatility, Sharpe, beta,
  correlation) are `None`/dropped below a minimum number of observations
  rather than computed from a handful of points.

The valuation-screener tie-in (flagging holdings via cluster membership) was
explicitly descoped and is not here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

import numpy as np
import pandas as pd

BASE_CURRENCY = "USD"

# currency -> friendly name of the pipeline series holding USD per 1 unit of
# that currency (see constants.ASSET_CLASS_TICKERS["fx"]). Adding a currency
# is one line here plus its ticker in constants.
FX_SERIES_BY_CURRENCY: dict[str, str] = {"CAD": "CADUSD_fx"}
SUPPORTED_CURRENCIES: tuple[str, ...] = (BASE_CURRENCY, *FX_SERIES_BY_CURRENCY)

BENCHMARK_TICKER = "SPY"          # beta benchmark (stored as "S&P500_ETF")
RISK_FREE_SERIES = "US13W_Yield"  # ^IRX, quoted in percentage points

ASSET_CLASS_CHOICES: tuple[str, ...] = ("stock", "etf", "fund", "bond", "commodity", "cash", "other")
PRICE_SOURCES: tuple[str, ...] = ("auto", "manual")

TRADING_DAYS_PER_YEAR = 252
MIN_OBS_STATS = 20          # volatility / Sharpe / beta
MIN_OBS_ANNUALIZE = 60      # annualised return
MIN_OBS_CORRELATION = 20
STALE_MANUAL_DAYS = 7

DIVIDEND_COLUMNS = ["id", "ticker", "pay_date", "amount", "currency", "fx_rate"]

HOLDING_COLUMNS = [
    "id", "ticker", "name", "asset_class", "sector", "currency", "price_source",
    "shares", "purchase_price", "purchase_date", "purchase_fx_rate",
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or (
        isinstance(value, str) and not value.strip()
    )


def _to_date(value: Any) -> date | None:
    """Parse a date / datetime / ISO string to a `date`, or None."""
    if _is_blank(value):
        return None
    try:
        return pd.Timestamp(value).date()
    except (ValueError, TypeError):
        return None


def _positive_number(value: Any) -> float | None:
    if _is_blank(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _series_by_key(df: pd.DataFrame | None, key: str, date_col: str, value_col: str) -> dict[str, pd.Series]:
    """Group a long frame into {key: Series(value, index=Timestamp)}, sorted,
    NaN-free, one value per date (last wins)."""
    if df is None or df.empty:
        return {}
    work = df[[key, date_col, value_col]].dropna(subset=[value_col]).copy()
    if work.empty:
        return {}
    work[date_col] = pd.to_datetime(work[date_col])
    out: dict[str, pd.Series] = {}
    for k, group in work.groupby(key):
        s = group.set_index(date_col)[value_col].astype(float).sort_index()
        out[k] = s[~s.index.duplicated(keep="last")]
    return out


def _seeded(seed_value: float, seed_date: pd.Timestamp, later: pd.Series) -> pd.Series:
    """`later` observations preceded by (seed_date, seed_value)."""
    seed = pd.Series([seed_value], index=pd.DatetimeIndex([seed_date]), dtype=float)
    return pd.concat([seed, later]) if len(later) else seed


def _on_grid(observations: pd.Series, grid: pd.DatetimeIndex) -> pd.Series:
    """Step-function (forward-filled) value of `observations` on `grid`.
    Observations on non-grid dates (e.g. a weekend purchase) still carry
    forward onto the next grid date."""
    obs = observations[~observations.index.duplicated(keep="last")].sort_index()
    return obs.reindex(obs.index.union(grid)).ffill().reindex(grid)


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FxRate:
    """USD per 1 unit of a currency, with where it came from."""

    rate: float
    as_of: date | None
    source: str  # "base" | "pipeline" | "manual"


def _fx_table(currency: str, pipeline_fx: pd.DataFrame | None, manual_fx: pd.DataFrame | None) -> pd.DataFrame:
    """Every known rate for `currency` as (date, rate, source), one row per
    date, manual winning over pipeline on the same date. `pipeline_fx` has
    columns date/rate; `manual_fx` has currency/as_of_date/rate."""
    frames = []
    if pipeline_fx is not None and not pipeline_fx.empty:
        p = pipeline_fx[["date", "rate"]].dropna(subset=["rate"]).copy()
        p["date"] = pd.to_datetime(p["date"])
        p["source"], p["_rank"] = "pipeline", 0
        frames.append(p)
    if manual_fx is not None and not manual_fx.empty:
        m = manual_fx[manual_fx["currency"] == currency][["as_of_date", "rate"]].dropna(subset=["rate"])
        m = m.rename(columns={"as_of_date": "date"}).copy()
        if not m.empty:
            m["date"] = pd.to_datetime(m["date"])
            m["source"], m["_rank"] = "manual", 1
            frames.append(m)
    if not frames:
        return pd.DataFrame(columns=["date", "rate", "source"])
    table = pd.concat(frames, ignore_index=True)
    table = table[table["rate"] > 0].sort_values(["date", "_rank"])
    table = table.drop_duplicates("date", keep="last").reset_index(drop=True)
    return table[["date", "rate", "source"]]


def resolve_current_fx(
    currency: str, pipeline_fx: pd.DataFrame | None, manual_fx: pd.DataFrame | None
) -> FxRate | None:
    """The rate to value positions at today: the most recent observation,
    manual winning ties. None if there is no rate at all (the page then
    flags the affected positions rather than guessing)."""
    if currency == BASE_CURRENCY:
        return FxRate(1.0, None, "base")
    table = _fx_table(currency, pipeline_fx, manual_fx)
    if table.empty:
        return None
    last = table.iloc[-1]
    return FxRate(float(last["rate"]), last["date"].date(), str(last["source"]))


def fx_rate_on(
    currency: str, on_date: date, pipeline_fx: pd.DataFrame | None, manual_fx: pd.DataFrame | None
) -> FxRate | None:
    """The rate in force on `on_date`: the latest observation on or before
    it (markets are closed at weekends). None if nothing is that old."""
    if currency == BASE_CURRENCY:
        return FxRate(1.0, None, "base")
    table = _fx_table(currency, pipeline_fx, manual_fx)
    if table.empty:
        return None
    eligible = table[table["date"] <= pd.Timestamp(on_date)]
    if eligible.empty:
        return None
    last = eligible.iloc[-1]
    return FxRate(float(last["rate"]), last["date"].date(), str(last["source"]))


# ---------------------------------------------------------------------------
# Entry validation (pure, so the rules are testable without Dash)
# ---------------------------------------------------------------------------

def validate_new_holding(
    *,
    ticker: Any,
    name: Any,
    asset_class: Any,
    sector: Any,
    currency: Any,
    price_source: Any,
    shares: Any,
    purchase_price: Any,
    purchase_date: Any,
    purchase_fx_rate: Any,
    pipeline_fx: pd.DataFrame | None,
    manual_fx: pd.DataFrame | None,
    today: date,
    has_price_history: bool | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Clean and check an "add position" form. Returns `(record, None)` ready
    for `PortfolioRepository.add_holding`, or `(None, error message)`.

    For a non-USD position the purchase-date FX rate is the value typed in,
    else the stored rate in force on the purchase date; if neither exists the
    position is rejected rather than saved with a guessed rate.
    `has_price_history` is whether the DB holds a market series for an
    auto-priced ticker (None = don't check).
    """
    if _is_blank(ticker):
        return None, "Enter a ticker."
    ticker = str(ticker).strip().upper()

    asset_class = str(asset_class).strip().lower() if not _is_blank(asset_class) else ""
    if asset_class not in ASSET_CLASS_CHOICES:
        return None, f"Choose an asset class ({', '.join(ASSET_CLASS_CHOICES)})."

    currency = str(currency).strip().upper() if not _is_blank(currency) else ""
    if currency not in SUPPORTED_CURRENCIES:
        return None, f"Currency must be one of {', '.join(SUPPORTED_CURRENCIES)}."

    price_source = str(price_source).strip().lower() if not _is_blank(price_source) else ""
    if price_source not in PRICE_SOURCES:
        return None, "Choose a price source (auto or manual)."

    shares_value = _positive_number(shares)
    if shares_value is None:
        return None, "Shares must be a positive number."
    price_value = _positive_number(purchase_price)
    if price_value is None:
        return None, "Purchase price must be a positive number."

    purchase = _to_date(purchase_date)
    if purchase is None:
        return None, "Enter a valid purchase date."
    if purchase > today:
        return None, "Purchase date can't be in the future."

    if price_source == "auto" and has_price_history is False:
        return None, (f"No stored price history for {ticker}. Choose manual pricing, or add the ticker to the "
                      "data pipeline and re-run it.")

    if currency == BASE_CURRENCY:
        fx_value = 1.0
    else:
        typed = _positive_number(purchase_fx_rate)
        if not _is_blank(purchase_fx_rate) and typed is None:
            return None, f"FX rate must be a positive number (USD per 1 {currency})."
        if typed is not None:
            fx_value = typed
        else:
            found = fx_rate_on(currency, purchase, pipeline_fx, manual_fx)
            if found is None:
                return None, (f"No {currency}->USD rate is stored for {purchase.isoformat()}. Enter the rate "
                              f"(USD per 1 {currency}) you got on that date.")
            fx_value = found.rate

    return {
        "ticker": ticker,
        "name": None if _is_blank(name) else str(name).strip(),
        "asset_class": asset_class,
        "sector": None if _is_blank(sector) else str(sector).strip(),
        "currency": currency,
        "price_source": price_source,
        "shares": shares_value,
        "purchase_price": price_value,
        "purchase_date": purchase,
        "purchase_fx_rate": fx_value,
    }, None


def validate_manual_price(
    *, ticker: Any, price: Any, as_of: Any, today: date, manual_tickers: dict[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    """`manual_tickers` maps each manually priced ticker to its currency; the
    mark is stored in that currency."""
    if _is_blank(ticker) or str(ticker).strip().upper() not in manual_tickers:
        return None, "Choose a manually priced position."
    ticker = str(ticker).strip().upper()
    price_value = _positive_number(price)
    if price_value is None:
        return None, "Price must be a positive number."
    as_of_date = _to_date(as_of)
    if as_of_date is None:
        return None, "Enter a valid as-of date."
    if as_of_date > today:
        return None, "As-of date can't be in the future."
    return {
        "ticker": ticker, "as_of_date": as_of_date, "price": price_value, "currency": manual_tickers[ticker],
    }, None


def validate_manual_fx(
    *, currency: Any, rate: Any, as_of: Any, today: date
) -> tuple[dict[str, Any] | None, str | None]:
    currency = str(currency).strip().upper() if not _is_blank(currency) else ""
    if currency not in FX_SERIES_BY_CURRENCY:
        return None, f"Choose a currency ({', '.join(FX_SERIES_BY_CURRENCY)})."
    rate_value = _positive_number(rate)
    if rate_value is None:
        return None, f"Rate must be a positive number (USD per 1 {currency})."
    as_of_date = _to_date(as_of)
    if as_of_date is None:
        return None, "Enter a valid as-of date."
    if as_of_date > today:
        return None, "As-of date can't be in the future."
    return {"currency": currency, "as_of_date": as_of_date, "rate": rate_value}, None


def validate_new_dividend(
    *,
    ticker: Any,
    pay_date: Any,
    amount: Any,
    fx_rate: Any,
    held: dict[str, tuple[str, date]],
    pipeline_fx: pd.DataFrame | None,
    manual_fx: pd.DataFrame | None,
    today: date,
) -> tuple[dict[str, Any] | None, str | None]:
    """Clean and check a "dividend received" form. `held` maps each held
    ticker to (currency, earliest purchase date); the dividend is stored in
    that currency. It must be paid after the first purchase. For a non-USD
    holding the pay-date FX is the value typed in, else the stored rate in
    force on the pay date, else the entry is rejected (never a guessed rate).
    """
    key = str(ticker).strip().upper() if not _is_blank(ticker) else ""
    if key not in held:
        return None, "Choose a position you hold."
    currency, first_purchase = held[key]

    amount_value = _positive_number(amount)
    if amount_value is None:
        return None, "Dividend amount must be a positive number (total cash received)."

    paid = _to_date(pay_date)
    if paid is None:
        return None, "Enter a valid pay date."
    if paid > today:
        return None, "Pay date can't be in the future."
    if paid <= first_purchase:
        return None, f"Pay date must be after you bought {key} ({first_purchase.isoformat()})."

    if currency == BASE_CURRENCY:
        fx_value = 1.0
    else:
        typed = _positive_number(fx_rate)
        if not _is_blank(fx_rate) and typed is None:
            return None, f"FX rate must be a positive number (USD per 1 {currency})."
        if typed is not None:
            fx_value = typed
        else:
            found = fx_rate_on(currency, paid, pipeline_fx, manual_fx)
            if found is None:
                return None, (f"No {currency}->USD rate is stored for {paid.isoformat()}. Enter the rate "
                              f"(USD per 1 {currency}).")
            fx_value = found.rate

    return {"ticker": key, "pay_date": paid, "amount": amount_value, "currency": currency, "fx_rate": fx_value}, None


# ---------------------------------------------------------------------------
# Current valuation
# ---------------------------------------------------------------------------

def latest_position_prices(
    holdings: pd.DataFrame, auto_prices: pd.DataFrame | None, manual_prices: pd.DataFrame | None
) -> pd.DataFrame:
    """Latest price per lot, in the lot's own currency.

    Columns: id, price_local, price_date, price_basis, where basis is
    "market" (latest stored close), "manual" (latest hand-entered mark on or
    after the purchase date), "cost" (manual position with no mark yet -- the
    purchase price is used so the position still counts, flagged downstream)
    or "missing" (auto position with no stored prices).

    `auto_prices` has ticker/date/close_price; `manual_prices` has
    ticker/as_of_date/price.
    """
    auto_by = _series_by_key(auto_prices, "ticker", "date", "close_price")
    manual_by = _series_by_key(manual_prices, "ticker", "as_of_date", "price")

    rows = []
    for h in holdings.itertuples(index=False):
        purchase = pd.Timestamp(h.purchase_date)
        if h.price_source == "manual":
            marks = manual_by.get(h.ticker)
            marks = marks[marks.index >= purchase] if marks is not None else None
            if marks is None or marks.empty:
                rows.append((h.id, float(h.purchase_price), purchase.date(), "cost"))
            else:
                rows.append((h.id, float(marks.iloc[-1]), marks.index[-1].date(), "manual"))
        else:
            closes = auto_by.get(h.ticker)
            if closes is None or closes.empty:
                rows.append((h.id, np.nan, None, "missing"))
            else:
                rows.append((h.id, float(closes.iloc[-1]), closes.index[-1].date(), "market"))
    return pd.DataFrame(rows, columns=["id", "price_local", "price_date", "price_basis"])


POSITION_COLUMNS = [
    *HOLDING_COLUMNS, "price_local", "price_date", "price_basis", "price_age_days", "fx_rate", "fx_source",
    "fx_as_of", "cost_basis_usd", "market_value_usd", "unrealized_pnl_usd", "unrealized_pnl_pct", "weight", "status",
]


def value_positions(
    holdings: pd.DataFrame,
    prices: pd.DataFrame,
    fx_by_currency: dict[str, FxRate | None],
    as_of: date,
) -> pd.DataFrame:
    """One row per lot with USD cost basis, USD market value, P&L, weight and
    a `status`. A lot that can't be valued (no price, or no FX rate) gets NaN
    value/P&L and a status saying why -- it is never silently valued at zero
    or at a guessed rate. A manual lot with no mark yet is valued at cost.
    """
    if holdings.empty:
        return pd.DataFrame(columns=POSITION_COLUMNS)

    df = holdings.merge(prices, on="id", how="left")

    def fx_for(currency: str) -> FxRate | None:
        if currency == BASE_CURRENCY:
            return FxRate(1.0, None, "base")
        return fx_by_currency.get(currency)

    fx_objs = [fx_for(c) for c in df["currency"]]
    df["fx_rate"] = [f.rate if f else np.nan for f in fx_objs]
    df["fx_source"] = [f.source if f else None for f in fx_objs]
    df["fx_as_of"] = [f.as_of if f else None for f in fx_objs]

    df["cost_basis_usd"] = df["shares"] * df["purchase_price"] * df["purchase_fx_rate"]
    df["market_value_usd"] = df["shares"] * df["price_local"] * df["fx_rate"]
    df["unrealized_pnl_usd"] = df["market_value_usd"] - df["cost_basis_usd"]
    df["unrealized_pnl_pct"] = df["unrealized_pnl_usd"] / df["cost_basis_usd"]

    total = df["market_value_usd"].sum(skipna=True)
    df["weight"] = df["market_value_usd"] / total if total > 0 else np.nan

    as_of_ts = pd.Timestamp(as_of)
    df["price_age_days"] = [
        np.nan if _is_blank(d) else float((as_of_ts - pd.Timestamp(d)).days) for d in df["price_date"]
    ]

    def status(row) -> str:
        if row["price_basis"] == "missing":
            return "no price data"
        if pd.isna(row["fx_rate"]):
            return f"no {row['currency']} FX rate"
        if row["price_basis"] == "cost":
            return "at cost (no manual price yet)"
        return "ok"

    df["status"] = df.apply(status, axis=1)
    return df[POSITION_COLUMNS]


def dividends_with_usd(dividends: pd.DataFrame | None) -> pd.DataFrame:
    """The dividend ledger with `amount_usd` = amount x pay-date FX."""
    if dividends is None or dividends.empty:
        return pd.DataFrame(columns=[*DIVIDEND_COLUMNS, "amount_usd"])
    out = dividends.copy()
    out["amount_usd"] = out["amount"].astype(float) * out["fx_rate"].astype(float)
    return out


def portfolio_totals(positions: pd.DataFrame, dividends: pd.DataFrame | None = None) -> dict[str, Any]:
    """Headline numbers over the lots that could be valued (P&L compares like
    with like: a lot with no value is excluded from both sides).

    `dividends` (the ledger) adds income received -- only for tickers that
    have at least one valued lot, for the same like-with-like reason. Total
    value is market value plus income; total return is unrealized P&L plus
    income, over cost."""
    empty = {"n_positions": 0, "n_unvalued": 0, "total_value_usd": 0.0, "total_cost_usd": 0.0,
             "unrealized_pnl_usd": 0.0, "unrealized_pnl_pct": None, "income_usd": 0.0,
             "total_value_with_income_usd": 0.0, "total_return_usd": 0.0, "total_return_pct": None}
    if positions.empty:
        return empty
    valued = positions[positions["market_value_usd"].notna()]
    value = float(valued["market_value_usd"].sum())
    cost = float(valued["cost_basis_usd"].sum())

    income = 0.0
    div = dividends_with_usd(dividends)
    if not div.empty:
        income = float(div.loc[div["ticker"].isin(set(valued["ticker"])), "amount_usd"].sum())
    return {
        "n_positions": int(len(positions)),
        "n_unvalued": int(len(positions) - len(valued)),
        "total_value_usd": value,
        "total_cost_usd": cost,
        "unrealized_pnl_usd": value - cost,
        "unrealized_pnl_pct": (value - cost) / cost if cost > 0 else None,
        "income_usd": income,
        "total_value_with_income_usd": value + income,
        "total_return_usd": value - cost + income,
        "total_return_pct": (value - cost + income) / cost if cost > 0 else None,
    }


def allocation(positions: pd.DataFrame, by: str) -> pd.DataFrame:
    """USD market value and weight per `by` bucket (e.g. "asset_class",
    "sector"), largest first. Blank buckets become "Unclassified"; lots that
    couldn't be valued are left out."""
    if positions.empty:
        return pd.DataFrame(columns=["label", "market_value_usd", "weight"])
    valued = positions[positions["market_value_usd"].notna()].copy()
    if valued.empty:
        return pd.DataFrame(columns=["label", "market_value_usd", "weight"])
    valued["label"] = valued[by].where(valued[by].notna() & (valued[by].astype(str).str.strip() != ""), "Unclassified")
    out = valued.groupby("label", as_index=False)["market_value_usd"].sum()
    out = out.sort_values("market_value_usd", ascending=False).reset_index(drop=True)
    out["weight"] = out["market_value_usd"] / out["market_value_usd"].sum()
    return out


# ---------------------------------------------------------------------------
# History, returns, risk
# ---------------------------------------------------------------------------

def build_usd_price_panel(
    holdings: pd.DataFrame,
    auto_prices: pd.DataFrame | None,
    manual_prices: pd.DataFrame | None,
    pipeline_fx_by_currency: dict[str, pd.DataFrame],
    manual_fx: pd.DataFrame | None,
) -> pd.DataFrame:
    """USD price per share for every lot on a business-day grid.

    Columns are lot ids, index is the date. A lot is NaN before its purchase
    date. Its local price is the purchase price on the purchase date, then
    the market closes (auto) or hand-entered marks (manual) after it, each
    held flat until the next observation. A non-USD lot's FX path is the
    purchase-date rate, then the stored rates after it; if no FX rate exists
    for that currency the lot is all-NaN (excluded) rather than frozen at the
    purchase rate, which would silently misstate its value.
    """
    if holdings.empty:
        return pd.DataFrame()

    h = holdings.copy()
    h["purchase_ts"] = pd.to_datetime(h["purchase_date"])
    auto_by = _series_by_key(auto_prices, "ticker", "date", "close_price")
    manual_by = _series_by_key(manual_prices, "ticker", "as_of_date", "price")
    fx_tables = {
        ccy: _fx_table(ccy, pipeline_fx_by_currency.get(ccy), manual_fx)
        for ccy in set(h["currency"]) - {BASE_CURRENCY}
    }

    # End of the grid: the last *price* observation (FX can run ahead of prices
    # and shouldn't stretch the chart with flat lines).
    candidates = [h["purchase_ts"].max()]
    for series in [*auto_by.values(), *manual_by.values()]:
        if len(series):
            candidates.append(series.index.max())
    # Roll weekend ends forward to Monday so a lot bought on a weekend (with
    # nothing priced after it yet) still gets its first row.
    roll = pd.offsets.BDay().rollforward
    grid = pd.bdate_range(roll(h["purchase_ts"].min().normalize()), roll(max(candidates).normalize()))
    if len(grid) == 0:
        return pd.DataFrame()

    columns: dict[int, pd.Series] = {}
    for row in h.itertuples(index=False):
        purchase = row.purchase_ts
        source = manual_by if row.price_source == "manual" else auto_by
        marks = source.get(row.ticker, pd.Series(dtype=float, index=pd.DatetimeIndex([])))
        local = _on_grid(_seeded(float(row.purchase_price), purchase, marks[marks.index > purchase]), grid)

        if row.currency == BASE_CURRENCY:
            fx = pd.Series(1.0, index=grid)
        else:
            table = fx_tables.get(row.currency)
            if table is None or table.empty:
                fx = pd.Series(np.nan, index=grid)
            else:
                later = table[table["date"] > purchase].set_index("date")["rate"].astype(float)
                fx = _on_grid(_seeded(float(row.purchase_fx_rate), purchase, later), grid)

        usd = local * fx
        usd[grid < purchase] = np.nan
        columns[int(row.id)] = usd

    panel = pd.DataFrame(columns, index=grid)
    panel.index.name = "date"
    return panel


def restrict_to_trading_days(panel: pd.DataFrame, trading_days: pd.DatetimeIndex | None) -> pd.DataFrame:
    """Drop business days the market was closed, so a holiday isn't counted
    as a zero-return day (which dampens volatility and beta). Only applied
    inside the range `trading_days` actually covers."""
    if panel.empty or trading_days is None or len(trading_days) == 0:
        return panel
    td = pd.DatetimeIndex(trading_days)
    keep = panel.index.isin(td) | (panel.index < td.min()) | (panel.index > td.max())
    restricted = panel.loc[keep]
    return restricted if len(restricted) >= 2 else panel


def portfolio_returns(usd_prices: pd.DataFrame, shares: pd.Series, income: pd.DataFrame | None = None) -> pd.Series:
    """Daily time-weighted portfolio return in USD.

    For each day, the return of the lots held at the previous close weighted
    by their previous-close USD value. A lot bought on day t has no previous
    close on day t, so it contributes from t+1 -- new money never shows up as
    performance.

    `income` (USD cash received per lot per day, same index/columns as
    `usd_prices`) is added to the numerator on the day it arrives, for lots
    held at the previous close: a dividend is a return, not new money.
    """
    if usd_prices.empty:
        return pd.Series(dtype=float)
    shares = shares.reindex(usd_prices.columns)
    values = usd_prices.mul(shares, axis=1)
    prev_value = values.shift(1)
    asset_return = usd_prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)

    contribution = (prev_value * asset_return).sum(axis=1, min_count=1)
    if income is not None and not income.empty:
        held = prev_value.notna() & asset_return.notna()
        received = income.reindex(index=usd_prices.index, columns=usd_prices.columns).fillna(0.0).where(held, 0.0)
        contribution = contribution + received.sum(axis=1)
    base = prev_value.where(asset_return.notna()).sum(axis=1, min_count=1)
    result = (contribution / base.where(base > 0)).dropna()
    return result.astype(float)


def income_by_lot(
    dividends: pd.DataFrame | None, holdings: pd.DataFrame, lot_ids: Iterable[int], grid: pd.DatetimeIndex
) -> pd.DataFrame:
    """USD dividend cash per lot per grid day. A dividend lands on the first
    grid day on or after its pay date (clamped to the last day) and is shared
    across that ticker's lots bought before the pay date, by shares. Empty
    (zero) frame when there is nothing to allocate."""
    lot_ids = list(lot_ids)
    out = pd.DataFrame(0.0, index=grid, columns=lot_ids)
    div = dividends_with_usd(dividends)
    if div.empty or len(grid) == 0 or not lot_ids:
        return out
    lots = holdings[holdings["id"].isin(lot_ids)].copy()
    lots["purchase_ts"] = pd.to_datetime(lots["purchase_date"])
    for d in div.itertuples(index=False):
        pay_ts = pd.Timestamp(d.pay_date)
        eligible = lots[(lots["ticker"] == d.ticker) & (lots["purchase_ts"] < pay_ts)]
        total_shares = float(eligible["shares"].sum())
        if eligible.empty or total_shares <= 0:
            continue
        pos = min(int(grid.searchsorted(pay_ts)), len(grid) - 1)
        for lot in eligible.itertuples(index=False):
            out.iloc[pos, out.columns.get_loc(int(lot.id))] += d.amount_usd * float(lot.shares) / total_shares
    return out


def daily_returns(prices: pd.Series) -> pd.Series:
    """Simple daily returns of a price series (Timestamp index)."""
    s = prices.dropna().sort_index()
    return s.pct_change(fill_method=None).dropna()


def risk_return_stats(
    returns: pd.Series, benchmark_returns: pd.Series | None = None, risk_free_rate: float | None = None
) -> dict[str, Any]:
    """Headline return/risk numbers from daily returns.

    `risk_free_rate` is an annual decimal (0.0425 = 4.25%). Each statistic is
    None when there isn't enough data to say anything sensible (see
    MIN_OBS_*), rather than a number from a handful of days.
    """
    r = returns.dropna()
    n = len(r)
    out: dict[str, Any] = {
        "n_obs": n, "start": r.index[0].date() if n else None, "end": r.index[-1].date() if n else None,
        "twr_total": None, "twr_annualized": None, "volatility": None, "sharpe": None, "beta": None,
        "beta_n_obs": 0, "max_drawdown": None, "risk_free_rate": risk_free_rate,
    }
    if n == 0:
        return out

    wealth = (1 + r).cumprod()
    out["twr_total"] = float(wealth.iloc[-1] - 1)
    if n >= MIN_OBS_ANNUALIZE and wealth.iloc[-1] > 0:
        out["twr_annualized"] = float(wealth.iloc[-1] ** (TRADING_DAYS_PER_YEAR / n) - 1)

    path = np.concatenate([[1.0], wealth.to_numpy()])
    out["max_drawdown"] = float((path / np.maximum.accumulate(path) - 1).min())

    if n >= MIN_OBS_STATS:
        std = float(r.std(ddof=1))
        if std > 1e-12:     # floating-point noise from a flat series is not volatility
            out["volatility"] = std * math.sqrt(TRADING_DAYS_PER_YEAR)
            if risk_free_rate is not None:
                excess = float(r.mean()) - risk_free_rate / TRADING_DAYS_PER_YEAR
                out["sharpe"] = excess / std * math.sqrt(TRADING_DAYS_PER_YEAR)
        else:
            out["volatility"] = 0.0

    if benchmark_returns is not None and len(benchmark_returns):
        joined = pd.concat([r.rename("p"), benchmark_returns.rename("b")], axis=1, join="inner").dropna()
        out["beta_n_obs"] = len(joined)
        if len(joined) >= MIN_OBS_STATS:
            var_b = float(joined["b"].var(ddof=1))
            if var_b > 0:
                out["beta"] = float(joined["p"].cov(joined["b"]) / var_b)
    return out


def correlation_matrix(
    usd_prices: pd.DataFrame, labels: dict[int, str], eligible_ids: Iterable[int], min_obs: int = MIN_OBS_CORRELATION,
) -> pd.DataFrame:
    """Correlation of daily USD returns between positions, labelled by
    ticker. Only `eligible_ids` are used (market-priced lots -- a manual
    position's flat-between-marks prices would produce meaningless
    correlations). A series with fewer than `min_obs` returns or zero
    variance is dropped (its correlation is undefined, not zero); lots of the
    same ticker appear once. Empty if fewer than two series survive.
    """
    cols = [c for c in eligible_ids if c in usd_prices.columns]
    if len(cols) < 2:
        return pd.DataFrame()
    rets = usd_prices[cols].pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    rets.columns = [labels.get(c, str(c)) for c in cols]
    rets = rets.loc[:, ~rets.columns.duplicated(keep="first")]
    keep = [c for c in rets.columns if rets[c].count() >= min_obs and rets[c].std() > 0]
    if len(keep) < 2:
        return pd.DataFrame()
    return rets[keep].corr(min_periods=min_obs)


@dataclass
class PortfolioAnalytics:
    value_history: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    cost_history: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    stats: dict[str, Any] = field(default_factory=dict)
    correlation: pd.DataFrame = field(default_factory=pd.DataFrame)
    excluded_labels: list[str] = field(default_factory=list)
    includes_manual: bool = False
    # market value + cumulative dividends received, by day (== value_history if none)
    total_value_history: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    has_income: bool = False


def analyze_portfolio(
    holdings: pd.DataFrame,
    auto_prices: pd.DataFrame | None,
    manual_prices: pd.DataFrame | None,
    pipeline_fx_by_currency: dict[str, pd.DataFrame],
    manual_fx: pd.DataFrame | None,
    benchmark_prices: pd.DataFrame | None,
    risk_free_rate: float | None,
    dividends: pd.DataFrame | None = None,
) -> PortfolioAnalytics:
    """History, time-weighted return, risk stats and correlation for the
    whole portfolio. Lots that can't be put on a USD price path (e.g. a CAD
    lot with no FX rate) are left out and named in `excluded_labels`.

    With `dividends`, returns and the headline stats are total returns
    (price + income); `stats["twr_price_total"]` / `["twr_price_annualized"]`
    then give the price-only figures for comparison."""
    if holdings.empty:
        return PortfolioAnalytics(stats=risk_return_stats(pd.Series(dtype=float), None, risk_free_rate))

    panel = build_usd_price_panel(holdings, auto_prices, manual_prices, pipeline_fx_by_currency, manual_fx)
    if panel.empty:
        return PortfolioAnalytics(stats=risk_return_stats(pd.Series(dtype=float), None, risk_free_rate))

    by_id = holdings.set_index("id")
    usable = [c for c in panel.columns if panel[c].notna().any()]
    excluded = [str(by_id.loc[c, "ticker"]) for c in panel.columns if c not in usable]
    panel = panel[usable]
    if panel.empty:
        return PortfolioAnalytics(excluded_labels=excluded,
                                  stats=risk_return_stats(pd.Series(dtype=float), None, risk_free_rate))

    shares = by_id.loc[usable, "shares"].astype(float)
    value_history = panel.mul(shares, axis=1).sum(axis=1, min_count=1).dropna()

    cost = by_id.loc[usable].copy()
    cost["cost_usd"] = cost["shares"] * cost["purchase_price"] * cost["purchase_fx_rate"]
    cost["purchase_ts"] = pd.to_datetime(cost["purchase_date"])
    cost_steps = cost.groupby("purchase_ts")["cost_usd"].sum().sort_index().cumsum()
    cost_history = cost_steps.reindex(cost_steps.index.union(panel.index)).ffill().reindex(panel.index).fillna(0.0)

    benchmark = None
    trading_days = None
    bench_by = _series_by_key(benchmark_prices, "ticker", "date", "close_price")
    if BENCHMARK_TICKER in bench_by:
        bench_prices = bench_by[BENCHMARK_TICKER]
        benchmark = daily_returns(bench_prices)
        trading_days = pd.DatetimeIndex(bench_prices.index)

    stat_panel = restrict_to_trading_days(panel, trading_days)

    lot_income = income_by_lot(dividends, holdings, usable, panel.index)
    has_income = bool(lot_income.to_numpy().sum() > 0)
    cum_income = lot_income.sum(axis=1).cumsum()
    total_value_history = value_history + cum_income.reindex(value_history.index).fillna(0.0)

    stat_income = None
    if has_income:
        # Income on a day dropped as a market holiday rolls into the next kept day.
        cum_lot = lot_income.cumsum().reindex(stat_panel.index)
        stat_income = cum_lot.diff().fillna(cum_lot)
    price_returns = portfolio_returns(stat_panel, shares)
    returns = portfolio_returns(stat_panel, shares, stat_income) if has_income else price_returns
    stats = risk_return_stats(returns, benchmark, risk_free_rate)
    if has_income:
        price_stats = risk_return_stats(price_returns)
        stats["twr_price_total"] = price_stats["twr_total"]
        stats["twr_price_annualized"] = price_stats["twr_annualized"]

    labels = {int(i): str(t) for i, t in by_id["ticker"].items()}
    market_ids = [int(i) for i in usable if by_id.loc[i, "price_source"] == "auto"]
    correlation = correlation_matrix(stat_panel, labels, market_ids)

    includes_manual = any(by_id.loc[i, "price_source"] == "manual" for i in usable)
    return PortfolioAnalytics(
        value_history=value_history, cost_history=cost_history, returns=returns, stats=stats,
        correlation=correlation, excluded_labels=excluded, includes_manual=includes_manual,
        total_value_history=total_value_history, has_income=has_income,
    )
