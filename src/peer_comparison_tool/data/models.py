"""
ORM schema for the data layer.

This replaces `data/db_tables.py`. A few deliberate changes from the original:

- All columns use snake_case Python attribute names (no more `"Basic EPS"`
  quoted-identifier SQL). Where useful, `.name` on `mapped_column` keeps the
  underlying DB column readable too.
- Every model has an explicit composite primary key matching how it's
  actually queried (ticker+date, sub_industry+date, etc.) — same as before,
  just declared once instead of duplicated across DDL strings and pandas
  column-list constants.
- No DROP TABLE anywhere. Schema changes go through Alembic migrations
  (see data/migrations/), not by editing and re-running this file.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CompanyInfo(Base):
    """Static-ish reference data for a stock ticker."""

    __tablename__ = "company_info"

    ticker: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    sector: Mapped[str]
    industry: Mapped[str | None]
    sub_industry: Mapped[str | None]


class TickerTimeSeries(Base):
    """Daily close price series for a single stock ticker."""

    __tablename__ = "ticker_time_series"

    ticker: Mapped[str] = mapped_column(ForeignKey("company_info.ticker"), primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    close_price: Mapped[float | None]
    close_price_indexed: Mapped[float | None]


class TickerTimeSeriesYoY(Base):
    """Year-over-year % change derived from TickerTimeSeries."""

    __tablename__ = "ticker_ts_yoy"

    ticker: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    close_price_yoy: Mapped[float | None]
    close_price_indexed_yoy: Mapped[float | None]


class AssetClassTimeSeries(Base):
    """Daily series for non-stock assets: commodities, indices, ETFs, FX."""

    __tablename__ = "asset_class_time_series"

    ticker: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    asset_class: Mapped[str | None] = mapped_column("AssetClass")
    close_price: Mapped[float | None]
    close_price_indexed: Mapped[float | None]
    close_price_yoy: Mapped[float | None]


class EconomicReleaseData(Base):
    """One value per (FRED series, release date) -- CPI, JOLTS job openings,
    nonfarm payrolls, unemployment rate, Fed funds rate, etc. See
    `data/clients/fred_client.py` and `data/transforms/economic_releases.py`.
    """

    __tablename__ = "economic_release_data"

    series_id: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    value: Mapped[float | None]


class QuarterlyFinancialData(Base):
    """Per-ticker quarterly income-statement-derived metrics."""

    __tablename__ = "quarterly_financial_data"

    ticker: Mapped[str] = mapped_column(ForeignKey("company_info.ticker"), primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    quarter_reporting: Mapped[str]
    basic_eps: Mapped[float | None] = mapped_column("basic_eps")
    operating_income: Mapped[float | None]
    operating_income_mm: Mapped[float | None]
    net_income: Mapped[float | None]
    net_income_mm: Mapped[float | None]
    gross_margin: Mapped[float | None]
    operating_margin: Mapped[float | None]
    net_margin: Mapped[float | None]
    ebitda_margin: Mapped[float | None]


class QuarterlyFinancialDataYoY(Base):
    __tablename__ = "ticker_metrics_yoy"

    ticker: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    quarter_reporting: Mapped[str]
    basic_eps_yoy: Mapped[float | None]
    operating_income_yoy: Mapped[float | None]
    net_income_yoy: Mapped[float | None]
    gross_margin_yoy: Mapped[float | None]
    operating_margin_yoy: Mapped[float | None]
    net_margin_yoy: Mapped[float | None]
    ebitda_margin_yoy: Mapped[float | None]


class BalanceSheetData(Base):
    """Per-ticker annual balance-sheet-derived metrics."""

    __tablename__ = "balance_sheet_data"

    ticker: Mapped[str] = mapped_column(ForeignKey("company_info.ticker"), primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    annual_reporting: Mapped[str]
    ordinary_shares_number: Mapped[int | None]
    stockholders_equity: Mapped[int | None]
    total_liabilities_net_minority_interest: Mapped[float | None]
    current_assets: Mapped[float | None]
    quick_ratio: Mapped[float | None]
    equity_ratio: Mapped[float | None]
    debt_to_equity_ratio: Mapped[float | None]


class CashflowStatementData(Base):
    __tablename__ = "cashflow_statement_data"

    ticker: Mapped[str] = mapped_column(ForeignKey("company_info.ticker"), primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    free_cash_flow: Mapped[float | None]
    operating_cash_flow: Mapped[float | None]
    capital_expenditure: Mapped[float | None]


class TickerMostRecentMetric(Base):
    """Latest snapshot of key valuation metrics per ticker (overwritten each refresh)."""

    __tablename__ = "ticker_most_recent_metric_data"

    ticker: Mapped[str] = mapped_column(ForeignKey("company_info.ticker"), primary_key=True)
    market_cap: Mapped[float | None]
    price_eps_ratio: Mapped[float | None]
    price_to_book: Mapped[float | None]
    return_on_equity: Mapped[float | None]
    debt_to_equity_ratio: Mapped[float | None]
    profit_margin: Mapped[float | None]
    enterprise_to_ebitda: Mapped[float | None]
    latest_eps: Mapped[float | None]
    enterprise_value: Mapped[float | None]


class ClusterMembership(Base):
    """DBSCAN valuation-cluster label per ticker, per run date."""

    __tablename__ = "cluster_table"

    ticker: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    cluster_membership: Mapped[str | None]


class IndustryTimeSeries(Base):
    __tablename__ = "industry_time_series"

    sub_industry: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    industry_close_price: Mapped[float | None]
    industry_close_price_indexed: Mapped[float | None]


class IndustryTimeSeriesYoY(Base):
    __tablename__ = "industry_time_series_yoy"

    sub_industry: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    industry_close_price_yoy: Mapped[float | None]
    industry_close_price_indexed_yoy: Mapped[float | None]


class IndustryMetrics(Base):
    __tablename__ = "industry_metrics"

    sub_industry: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    quarter_reporting: Mapped[str]
    basic_eps: Mapped[float | None]
    operating_income: Mapped[float | None]
    net_income: Mapped[float | None]
    gross_margin: Mapped[float | None]
    operating_margin: Mapped[float | None]
    net_margin: Mapped[float | None]
    ebitda_margin: Mapped[float | None]


class IndustryMetricsYoY(Base):
    __tablename__ = "industry_metrics_yoy"

    sub_industry: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    quarter_reporting: Mapped[str]
    basic_eps_yoy: Mapped[float | None]
    operating_income_yoy: Mapped[float | None]
    net_income_yoy: Mapped[float | None]
    gross_margin_yoy: Mapped[float | None]
    operating_margin_yoy: Mapped[float | None]
    net_margin_yoy: Mapped[float | None]
    ebitda_margin_yoy: Mapped[float | None]


class DataStorageRecord(Base):
    """Tracks the last successful fetch date per ticker/asset — drives the recency checks
    that decide whether main_run() needs to hit the API again."""

    __tablename__ = "data_storage_record"

    ticker: Mapped[str] = mapped_column(primary_key=True)
    version_date: Mapped[date] = mapped_column("version_date", primary_key=True)


# ---------------------------------------------------------------------------
# Portfolio tracking (user-entered data -- not produced by the pipeline)
# ---------------------------------------------------------------------------

class PortfolioHolding(Base):
    """One purchase lot in the user's portfolio.

    Several lots of the same ticker are separate rows (different purchase
    date/price/FX), which is what makes cost basis and P&L exact.

    `purchase_price` is per share in the position's own `currency`;
    `purchase_fx_rate` is USD per 1 unit of that currency on the purchase
    date (1.0 for USD), frozen at entry so USD cost basis includes the FX
    move since purchase. `price_source` is "auto" (priced from the stored
    market series) or "manual" (priced from `ManualPrice` -- for positions
    the pipeline can't see, e.g. CAD-hedged funds).

    `ticker` is deliberately not a foreign key: manual-priced positions
    usually aren't in `company_info`.
    """

    __tablename__ = "portfolio_holding"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str]
    name: Mapped[str | None]
    asset_class: Mapped[str]
    sector: Mapped[str | None]
    currency: Mapped[str]
    price_source: Mapped[str]
    shares: Mapped[float]
    purchase_price: Mapped[float]
    purchase_date: Mapped[date]
    purchase_fx_rate: Mapped[float]


class ManualPrice(Base):
    """Hand-entered price mark for a manually priced position. One row per
    (ticker, as-of date); entering a price for an existing date replaces it.
    `price` is per share in `currency` (which must match the holding's
    currency -- enforced at entry in `transforms/portfolio.py`)."""

    __tablename__ = "manual_price"

    ticker: Mapped[str] = mapped_column(primary_key=True)
    as_of_date: Mapped[date] = mapped_column(primary_key=True)
    price: Mapped[float]
    currency: Mapped[str]


class ManualFxRate(Base):
    """Hand-entered FX override: USD per 1 unit of `currency` on `as_of_date`.
    The portfolio uses it in preference to the pipeline's series whenever it
    is at least as recent (see `transforms/portfolio.resolve_current_fx`)."""

    __tablename__ = "manual_fx_rate"

    currency: Mapped[str] = mapped_column(primary_key=True)
    as_of_date: Mapped[date] = mapped_column(primary_key=True)
    rate: Mapped[float]


class PortfolioDividend(Base):
    """A cash dividend / distribution the user received, entered by hand.

    `amount` is the total cash received (not per share) in `currency`, which
    is the currency of the ticker's holding; `fx_rate` is USD per 1 unit of
    that currency on `pay_date` (1.0 for USD), frozen at entry. It is income:
    it counts towards total value and total return but is not reinvested.
    `ticker` is not a foreign key for the same reason as `PortfolioHolding`.
    """

    __tablename__ = "portfolio_dividend"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str]
    pay_date: Mapped[date]
    amount: Mapped[float]
    currency: Mapped[str]
    fx_rate: Mapped[float]
