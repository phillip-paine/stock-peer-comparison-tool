"""PortfolioRepository against the real in-memory DB (the `session` fixture):
the portfolio's reads and writes, and the lookups that bridge it to the
pipeline's tables."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from peer_comparison_tool.data.models import AssetClassTimeSeries, CompanyInfo, TickerTimeSeries
from peer_comparison_tool.data.portfolio_repository import PortfolioRepository


def _add(repo, ticker="AAA", purchase=date(2026, 1, 5), source="auto", currency="USD", shares=10.0, price=100.0, fx=1.0):
    return repo.add_holding(
        ticker=ticker, name=None, asset_class="stock", sector=None, currency=currency, price_source=source,
        shares=shares, purchase_price=price, purchase_date=purchase, purchase_fx_rate=fx,
    )


def test_added_holdings_come_back_oldest_first_with_real_dates(session):
    repo = PortfolioRepository(session)
    newer = _add(repo, "NEW", purchase=date(2026, 6, 1))
    older = _add(repo, "OLD", purchase=date(2026, 1, 5))
    assert newer < older          # ids follow insertion order...

    df = repo.list_holdings()
    assert df["ticker"].tolist() == ["OLD", "NEW"]        # ...but the list follows purchase date
    assert df["purchase_date"].iloc[0] == date(2026, 1, 5)    # a date, not a unix-nanosecond integer
    assert df["name"].isna().all()                          # NULLs stay missing, not "None"/"nan" strings
    assert df["shares"].dtype == float


def test_list_holdings_when_empty(session):
    assert PortfolioRepository(session).list_holdings().empty


def test_deleting_a_lot_removes_marks_only_for_tickers_no_longer_held(session):
    repo = PortfolioRepository(session)
    fund_a = _add(repo, "FUND", source="manual", purchase=date(2026, 1, 5))
    fund_b = _add(repo, "FUND", source="manual", purchase=date(2026, 2, 5))
    other = _add(repo, "OTHER", source="manual")
    repo.upsert_manual_price("FUND", date(2026, 3, 1), 101.0, "USD")
    repo.upsert_manual_price("OTHER", date(2026, 3, 1), 7.0, "USD")

    # One of two FUND lots goes: FUND is still held, so its marks stay.
    assert repo.delete_holdings([fund_a]) == 1
    assert set(repo.manual_prices()["ticker"]) == {"FUND", "OTHER"}

    # The last FUND lot goes: its marks are dropped so a later re-add starts clean.
    assert repo.delete_holdings([fund_b, 9999]) == 1      # unknown ids are ignored
    assert set(repo.manual_prices()["ticker"]) == {"OTHER"}
    assert repo.list_holdings()["id"].tolist() == [other]


def test_delete_with_no_ids_is_a_no_op(session):
    repo = PortfolioRepository(session)
    _add(repo)
    assert repo.delete_holdings([]) == 0
    assert len(repo.list_holdings()) == 1


def test_a_manual_price_for_the_same_date_is_replaced_not_duplicated(session):
    repo = PortfolioRepository(session)
    repo.upsert_manual_price("FUND", date(2026, 3, 1), 100.0, "CAD")
    repo.upsert_manual_price("FUND", date(2026, 3, 1), 103.5, "CAD")
    repo.upsert_manual_price("FUND", date(2026, 4, 1), 104.0, "CAD")
    df = repo.manual_prices().sort_values("as_of_date")
    assert df["price"].tolist() == [103.5, 104.0]
    assert set(df["currency"]) == {"CAD"}


def test_a_manual_fx_rate_for_the_same_date_is_replaced(session):
    repo = PortfolioRepository(session)
    repo.upsert_manual_fx_rate("CAD", date(2026, 3, 1), 0.70)
    repo.upsert_manual_fx_rate("CAD", date(2026, 3, 1), 0.7312)
    df = repo.manual_fx_rates()
    assert len(df) == 1 and df["rate"].iloc[0] == pytest.approx(0.7312)


def _seed_market_data(session):
    session.add(CompanyInfo(ticker="AAPL", name="Apple Inc.", sector="Technology"))
    session.flush()
    repo = PortfolioRepository(session)
    repo.upsert_dataframe(TickerTimeSeries, pd.DataFrame({
        "ticker": "AAPL", "date": [date(2026, 10, 8), date(2026, 10, 9)], "close_price": [200.0, 205.0]}))
    # asset-class rows are stored under friendly names, not yfinance symbols
    repo.upsert_dataframe(AssetClassTimeSeries, pd.DataFrame({
        "ticker": ["S&P500_ETF"] * 2 + ["GoldFutures"] * 2 + ["CADUSD_fx"] * 2 + ["US13W_Yield"] * 3,
        "date": [date(2026, 10, 8), date(2026, 10, 9)] * 3 + [date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 10)],
        "close_price": [500.0, 505.0, 2000.0, 2010.0, 0.7300, 0.7312, 4.10, 4.25, None],
    }))
    return repo


def test_price_history_maps_asset_symbols_back_from_friendly_names(session):
    repo = _seed_market_data(session)
    df = repo.price_history(["AAPL", "SPY", "GC=F", "NOT_STORED"])
    assert set(df["ticker"]) == {"AAPL", "SPY", "GC=F"}      # the symbol the holding uses, never "S&P500_ETF"
    spy = df[df["ticker"] == "SPY"].sort_values("date")
    assert spy["close_price"].tolist() == [500.0, 505.0]
    assert all(isinstance(d, date) for d in df["date"])      # real dates, not timestamps or integers


def test_price_history_for_nothing_stored_has_the_expected_columns(session):
    df = PortfolioRepository(session).price_history(["NOPE"])
    assert df.empty and list(df.columns) == ["ticker", "date", "close_price"]
    assert PortfolioRepository(session).price_history([]).empty


def test_fx_history_reads_the_pipeline_series_as_usd_per_unit(session):
    repo = _seed_market_data(session)
    cad = repo.fx_history("CAD")
    assert list(cad.columns) == ["date", "rate"]
    assert cad.sort_values("date")["rate"].tolist() == [0.73, 0.7312]
    assert repo.fx_history("USD").empty and repo.fx_history("XYZ").empty


def test_latest_risk_free_rate_is_a_decimal_from_the_latest_non_null_close(session):
    repo = _seed_market_data(session)
    # 2026-10-10 has a NULL close, so the latest real value is 4.25 (percentage points) -> 0.0425
    assert repo.latest_risk_free_rate() == pytest.approx(0.0425)


def test_latest_risk_free_rate_is_none_when_not_stored(session):
    assert PortfolioRepository(session).latest_risk_free_rate() is None


def test_company_profile_for_prefilling_the_form(session):
    repo = _seed_market_data(session)
    assert repo.company_profile("AAPL") == {"name": "Apple Inc.", "sector": "Technology"}
    assert repo.company_profile("NOPE") is None


def test_new_fx_symbol_is_part_of_the_pipeline_universe():
    """The CAD->USD series the portfolio relies on must be in the asset universe the pipeline fetches."""
    from peer_comparison_tool.data.constants import asset_name_to_class, asset_symbol_to_name

    assert asset_symbol_to_name()["CADUSD=X"] == "CADUSD_fx"
    assert asset_name_to_class()["CADUSD_fx"] == "fx"


def test_dividends_round_trip_oldest_first_and_delete(session):
    repo = PortfolioRepository(session)
    _add(repo, "AAA")
    later = repo.add_dividend(ticker="AAA", pay_date=date(2026, 6, 1), amount=12.5, currency="USD", fx_rate=1.0)
    earlier = repo.add_dividend(ticker="AAA", pay_date=date(2026, 3, 1), amount=10.0, currency="USD", fx_rate=1.0)
    df = repo.list_dividends()
    assert df["id"].tolist() == [earlier, later]
    assert df["pay_date"].iloc[0] == date(2026, 3, 1)         # a date, not a timestamp
    assert repo.delete_dividends([earlier, 9999]) == 1 and repo.delete_dividends([]) == 0
    assert repo.list_dividends()["id"].tolist() == [later]


def test_dividends_for_a_ticker_no_longer_held_are_dropped_with_its_last_lot(session):
    repo = PortfolioRepository(session)
    keep, gone = _add(repo, "KEEP"), _add(repo, "GONE")
    repo.add_dividend(ticker="KEEP", pay_date=date(2026, 3, 1), amount=1.0, currency="USD", fx_rate=1.0)
    repo.add_dividend(ticker="GONE", pay_date=date(2026, 3, 1), amount=2.0, currency="USD", fx_rate=1.0)
    repo.delete_holdings([gone])
    assert repo.list_dividends()["ticker"].tolist() == ["KEEP"]


def test_list_dividends_when_empty(session):
    assert PortfolioRepository(session).list_dividends().empty
