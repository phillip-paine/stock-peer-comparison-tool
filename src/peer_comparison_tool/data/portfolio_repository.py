"""
Reads and writes for the portfolio feature, on top of `Repository`.

Kept in its own module because, unlike everything else in the data layer,
this is user-entered state that the dashboard writes at runtime (holdings,
hand-entered prices and FX rates) -- not data the pipeline materializes. The
generic `upsert()` / `fetch_dataframe()` from `Repository` are reused as-is.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import delete, select

from .constants import asset_symbol_to_name
from .models import (
    AssetClassTimeSeries,
    CompanyInfo,
    ManualFxRate,
    ManualPrice,
    PortfolioDividend,
    PortfolioHolding,
    TickerTimeSeries,
)
from .repository import Repository
from .transforms.portfolio import BASE_CURRENCY, FX_SERIES_BY_CURRENCY, RISK_FREE_SERIES

_PRICE_COLUMNS = ["ticker", "date", "close_price"]


class PortfolioRepository(Repository):
    # ---- holdings -----------------------------------------------------

    def list_holdings(self) -> pd.DataFrame:
        """Every lot, oldest purchase first."""
        df = self.fetch_dataframe(PortfolioHolding)
        if df.empty:
            return df
        return df.sort_values(["purchase_date", "id"]).reset_index(drop=True)

    def add_holding(self, **fields: Any) -> int:
        """Insert one lot (fields as produced by
        `transforms.portfolio.validate_new_holding`) and return its id."""
        row = PortfolioHolding(**fields)
        self._session.add(row)
        self._session.flush()
        return row.id

    def delete_holdings(self, ids: Iterable[int]) -> int:
        """Delete lots by id, then drop hand-entered prices for any ticker no
        lot holds any more, and likewise its dividends (so re-adding that ticker
        later doesn't resurrect old marks or income). Returns the number of lots deleted."""
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        result = self._session.execute(delete(PortfolioHolding).where(PortfolioHolding.id.in_(ids)))
        self._session.execute(delete(ManualPrice).where(ManualPrice.ticker.not_in(select(PortfolioHolding.ticker))))
        self._session.execute(
            delete(PortfolioDividend).where(PortfolioDividend.ticker.not_in(select(PortfolioHolding.ticker)))
        )
        return int(result.rowcount or 0)

    # ---- dividends received (entered by hand) ----------------------------

    def list_dividends(self) -> pd.DataFrame:
        """Every dividend, oldest first."""
        df = self.fetch_dataframe(PortfolioDividend)
        if df.empty:
            return df
        return df.sort_values(["pay_date", "id"]).reset_index(drop=True)

    def add_dividend(self, **fields: Any) -> int:
        """Insert one dividend (fields from `transforms.portfolio.validate_new_dividend`)."""
        row = PortfolioDividend(**fields)
        self._session.add(row)
        self._session.flush()
        return row.id

    def delete_dividends(self, ids: Iterable[int]) -> int:
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        result = self._session.execute(delete(PortfolioDividend).where(PortfolioDividend.id.in_(ids)))
        return int(result.rowcount or 0)

    # ---- manual prices / FX ------------------------------------------------

    def manual_prices(self) -> pd.DataFrame:
        return self.fetch_dataframe(ManualPrice)

    def upsert_manual_price(self, ticker: str, as_of_date: date, price: float, currency: str) -> None:
        """Add or replace the mark for (ticker, as_of_date)."""
        self.upsert(
            ManualPrice,
            [{"ticker": ticker, "as_of_date": as_of_date, "price": price, "currency": currency}],
            mode="replace",
        )

    def manual_fx_rates(self) -> pd.DataFrame:
        return self.fetch_dataframe(ManualFxRate)

    def upsert_manual_fx_rate(self, currency: str, as_of_date: date, rate: float) -> None:
        """Add or replace the override for (currency, as_of_date)."""
        self.upsert(
            ManualFxRate, [{"currency": currency, "as_of_date": as_of_date, "rate": rate}], mode="replace"
        )

    # ---- market data the portfolio reads ---------------------------------------

    def company_profile(self, ticker: str) -> dict[str, Any] | None:
        """Name and sector from `company_info`, to pre-fill the add form."""
        row = self._session.execute(
            select(CompanyInfo.name, CompanyInfo.sector).where(CompanyInfo.ticker == ticker)
        ).first()
        return None if row is None else {"name": row.name, "sector": row.sector}

    def price_history(self, tickers: Iterable[str]) -> pd.DataFrame:
        """Stored close prices as ticker/date/close_price, keyed by the
        *symbol the holding uses*. Stock tickers read `ticker_time_series`;
        yfinance symbols the pipeline tracks as asset classes (e.g. `SPY`,
        `GC=F`) read `asset_class_time_series`, where they are stored under a
        friendly name (`S&P500_ETF`) -- mapped back here so callers never see
        the friendly name."""
        symbols = sorted({str(t) for t in tickers})
        symbol_to_name = asset_symbol_to_name()
        asset_symbols = [s for s in symbols if s in symbol_to_name]
        stock_symbols = [s for s in symbols if s not in symbol_to_name]

        frames = []
        connection = self._session.connection()
        if stock_symbols:
            stmt = select(TickerTimeSeries.ticker, TickerTimeSeries.date, TickerTimeSeries.close_price).where(
                TickerTimeSeries.ticker.in_(stock_symbols)
            )
            frames.append(pd.read_sql(stmt, connection))
        if asset_symbols:
            name_to_symbol = {symbol_to_name[s]: s for s in asset_symbols}
            stmt = select(
                AssetClassTimeSeries.ticker, AssetClassTimeSeries.date, AssetClassTimeSeries.close_price
            ).where(AssetClassTimeSeries.ticker.in_(list(name_to_symbol)))
            df = pd.read_sql(stmt, connection)
            df["ticker"] = df["ticker"].map(name_to_symbol)
            frames.append(df)

        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame(columns=_PRICE_COLUMNS)
        return pd.concat(frames, ignore_index=True)

    def fx_history(self, currency: str) -> pd.DataFrame:
        """The pipeline's USD-per-1-unit series for `currency` as date/rate
        (empty for USD, for a currency with no series, or if the pipeline
        hasn't fetched it yet)."""
        series = FX_SERIES_BY_CURRENCY.get(currency)
        if currency == BASE_CURRENCY or series is None:
            return pd.DataFrame(columns=["date", "rate"])
        stmt = select(AssetClassTimeSeries.date, AssetClassTimeSeries.close_price).where(
            AssetClassTimeSeries.ticker == series
        )
        df = pd.read_sql(stmt, self._session.connection())
        return df.rename(columns={"close_price": "rate"})

    def latest_risk_free_rate(self) -> float | None:
        """Latest 13-week T-bill yield (`^IRX`, ingested as `US13W_Yield`) as
        an annual *decimal*. yfinance quotes it in percentage points (4.25
        means 4.25%), so it is divided by 100 here -- in one place, so no
        caller can forget. None if the series isn't stored."""
        value = self._session.execute(
            select(AssetClassTimeSeries.close_price)
            .where(AssetClassTimeSeries.ticker == RISK_FREE_SERIES, AssetClassTimeSeries.close_price.is_not(None))
            .order_by(AssetClassTimeSeries.date.desc())
            .limit(1)
        ).scalar_one_or_none()
        return None if value is None else float(value) / 100.0
