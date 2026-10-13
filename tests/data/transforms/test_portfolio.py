"""Tests for the pure portfolio maths (no DB, no Dash).

Fixtures are small synthetic frames shaped like what `PortfolioRepository`
returns, with hand-computable numbers so each expectation can be checked on
paper.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from peer_comparison_tool.data.transforms import portfolio as pf


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

def lot(id, ticker="AAA", currency="USD", source="auto", shares=10.0, price=100.0,
        purchase=date(2026, 1, 5), fx=1.0, asset_class="stock", sector="Technology", name=None):
    return {"id": id, "ticker": ticker, "name": name, "asset_class": asset_class, "sector": sector,
            "currency": currency, "price_source": source, "shares": shares, "purchase_price": price,
            "purchase_date": purchase, "purchase_fx_rate": fx}


def holdings(*lots) -> pd.DataFrame:
    return pd.DataFrame(list(lots))


def closes(ticker, dates, values) -> pd.DataFrame:
    return pd.DataFrame({"ticker": ticker, "date": [pd.Timestamp(d).date() for d in dates], "close_price": values})


def fx_series(dates, rates) -> pd.DataFrame:
    return pd.DataFrame({"date": [pd.Timestamp(d).date() for d in dates], "rate": rates})


def manual_fx(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["currency", "as_of_date", "rate"])


def manual_prices(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["ticker", "as_of_date", "price", "currency"])


NO_MANUAL_PRICES = manual_prices([])
NO_MANUAL_FX = manual_fx([])


# ---------------------------------------------------------------------------
# FX resolution
# ---------------------------------------------------------------------------

def test_usd_needs_no_rate():
    fx = pf.resolve_current_fx("USD", None, None)
    assert fx.rate == 1.0 and fx.source == "base"


def test_current_fx_prefers_a_newer_manual_rate():
    pipeline = fx_series(["2026-10-08"], [0.73])
    manual = manual_fx([("CAD", date(2026, 10, 9), 0.74)])
    fx = pf.resolve_current_fx("CAD", pipeline, manual)
    assert (fx.rate, fx.source, fx.as_of) == (0.74, "manual", date(2026, 10, 9))


def test_current_fx_ignores_a_stale_manual_rate():
    pipeline = fx_series(["2026-10-08"], [0.73])
    manual = manual_fx([("CAD", date(2026, 10, 7), 0.99)])
    fx = pf.resolve_current_fx("CAD", pipeline, manual)
    assert (fx.rate, fx.source) == (0.73, "pipeline")


def test_current_fx_manual_wins_a_same_day_tie():
    pipeline = fx_series(["2026-10-08"], [0.73])
    manual = manual_fx([("CAD", date(2026, 10, 8), 0.74)])
    assert pf.resolve_current_fx("CAD", pipeline, manual).source == "manual"


def test_current_fx_ignores_manual_rates_for_other_currencies():
    manual = manual_fx([("EUR", date(2026, 10, 9), 1.1)])
    assert pf.resolve_current_fx("CAD", None, manual) is None


def test_current_fx_none_when_nothing_is_stored():
    assert pf.resolve_current_fx("CAD", pd.DataFrame(columns=["date", "rate"]), NO_MANUAL_FX) is None


def test_fx_rate_on_uses_latest_rate_on_or_before_the_date():
    pipeline = fx_series(["2026-01-02", "2026-01-09"], [0.70, 0.71])
    sat = pf.fx_rate_on("CAD", date(2026, 1, 10), pipeline, NO_MANUAL_FX)   # a Saturday
    assert sat.rate == 0.71
    assert pf.fx_rate_on("CAD", date(2026, 1, 5), pipeline, NO_MANUAL_FX).rate == 0.70
    assert pf.fx_rate_on("CAD", date(2026, 1, 1), pipeline, NO_MANUAL_FX) is None


# ---------------------------------------------------------------------------
# Entry validation
# ---------------------------------------------------------------------------

TODAY = date(2026, 10, 11)
VALID = dict(ticker=" aapl ", name="", asset_class="stock", sector=" ", currency="USD", price_source="auto",
             shares=10, purchase_price=150.5, purchase_date="2026-03-02", purchase_fx_rate=None,
             pipeline_fx=None, manual_fx=None, today=TODAY, has_price_history=True)


def validate(**overrides):
    return pf.validate_new_holding(**{**VALID, **overrides})


def test_valid_usd_holding_is_normalised():
    record, error = validate(purchase_fx_rate=0.5)   # a typed FX rate is irrelevant for USD
    assert error is None
    assert record == {
        "ticker": "AAPL", "name": None, "asset_class": "stock", "sector": None, "currency": "USD",
        "price_source": "auto", "shares": 10.0, "purchase_price": 150.5, "purchase_date": date(2026, 3, 2),
        "purchase_fx_rate": 1.0,
    }


def test_cad_holding_takes_the_stored_rate_in_force_on_the_purchase_date():
    pipeline = fx_series(["2026-02-27", "2026-03-03"], [0.70, 0.71])
    record, error = validate(currency="CAD", price_source="manual", pipeline_fx=pipeline, manual_fx=NO_MANUAL_FX)
    assert error is None and record["purchase_fx_rate"] == 0.70   # 2026-03-02 is before the 03-03 observation


def test_cad_holding_prefers_a_typed_rate():
    pipeline = fx_series(["2026-02-27"], [0.70])
    record, _ = validate(currency="CAD", purchase_fx_rate=0.7123, pipeline_fx=pipeline, manual_fx=NO_MANUAL_FX)
    assert record["purchase_fx_rate"] == 0.7123


def test_cad_holding_with_no_rate_anywhere_is_rejected_not_guessed():
    record, error = validate(currency="CAD", price_source="manual", pipeline_fx=None, manual_fx=NO_MANUAL_FX)
    assert record is None and "No CAD->USD rate" in error


@pytest.mark.parametrize("overrides, fragment", [
    ({"ticker": "  "}, "ticker"),
    ({"asset_class": "meme"}, "asset class"),
    ({"currency": "EUR"}, "Currency"),
    ({"price_source": "guess"}, "price source"),
    ({"shares": 0}, "Shares"),
    ({"shares": -3}, "Shares"),
    ({"shares": None}, "Shares"),
    ({"purchase_price": "abc"}, "Purchase price"),
    ({"purchase_date": "not a date"}, "purchase date"),
    ({"purchase_date": date(2026, 10, 12)}, "future"),
    ({"has_price_history": False}, "No stored price history"),
])
def test_invalid_entries_are_rejected_with_a_reason(overrides, fragment):
    record, error = validate(**overrides)
    assert record is None and fragment.lower() in error.lower()


def test_manual_pricing_does_not_need_stored_history():
    record, error = validate(price_source="manual", has_price_history=False)
    assert error is None and record["price_source"] == "manual"


def test_validate_manual_price_uses_the_holdings_currency():
    record, error = pf.validate_manual_price(ticker="fund", price="101.25", as_of="2026-10-09", today=TODAY,
                                             manual_tickers={"FUND": "CAD"})
    assert error is None
    assert record == {"ticker": "FUND", "as_of_date": date(2026, 10, 9), "price": 101.25, "currency": "CAD"}


@pytest.mark.parametrize("kwargs", [
    dict(ticker="OTHER", price=1, as_of="2026-10-09"),     # not a manual position
    dict(ticker="FUND", price=0, as_of="2026-10-09"),
    dict(ticker="FUND", price=1, as_of="nonsense"),
    dict(ticker="FUND", price=1, as_of="2026-10-12"),      # future
])
def test_validate_manual_price_rejects_bad_input(kwargs):
    record, error = pf.validate_manual_price(today=TODAY, manual_tickers={"FUND": "CAD"}, **kwargs)
    assert record is None and error


def test_validate_manual_fx():
    record, error = pf.validate_manual_fx(currency="cad", rate=0.7312, as_of="2026-10-09", today=TODAY)
    assert error is None and record == {"currency": "CAD", "as_of_date": date(2026, 10, 9), "rate": 0.7312}
    for bad in (dict(currency="USD", rate=1, as_of="2026-10-09"), dict(currency="CAD", rate=-1, as_of="2026-10-09"),
                dict(currency="CAD", rate=0.7, as_of="2026-10-12")):
        assert pf.validate_manual_fx(today=TODAY, **bad)[0] is None


# ---------------------------------------------------------------------------
# Current prices and valuation
# ---------------------------------------------------------------------------

def test_latest_prices_market_manual_cost_and_missing():
    h = holdings(
        lot(1, "AAA", source="auto"),
        lot(2, "NOPE", source="auto"),
        lot(3, "FUND", source="manual", currency="CAD", fx=0.7),
        lot(4, "NEW", source="manual", price=55.0),
    )
    auto = closes("AAA", ["2026-10-08", "2026-10-09"], [111.0, 112.0])
    marks = manual_prices([
        ("FUND", date(2026, 1, 2), 90.0, "CAD"),      # before the purchase date: not a price for this lot
        ("FUND", date(2026, 3, 1), 101.0, "CAD"),
        ("FUND", date(2026, 9, 1), 104.0, "CAD"),
    ])
    out = pf.latest_position_prices(h, auto, marks).set_index("id")
    assert (out.loc[1, "price_local"], out.loc[1, "price_basis"], out.loc[1, "price_date"]) == (
        112.0, "market", date(2026, 10, 9))
    assert out.loc[2, "price_basis"] == "missing" and np.isnan(out.loc[2, "price_local"])
    assert (out.loc[3, "price_local"], out.loc[3, "price_basis"], out.loc[3, "price_date"]) == (
        104.0, "manual", date(2026, 9, 1))
    assert (out.loc[4, "price_local"], out.loc[4, "price_basis"]) == (55.0, "cost")   # no mark yet: at cost


def test_cad_position_pnl_includes_the_currency_move_since_purchase():
    h = holdings(
        lot(1, "AAPL", price=100.0, sector="Technology"),
        lot(2, "FUND", currency="CAD", source="manual", price=100.0, fx=0.70, asset_class="fund", sector=None),
    )
    prices = pd.DataFrame({"id": [1, 2], "price_local": [110.0, 100.0],
                           "price_date": [date(2026, 10, 9), date(2026, 10, 1)], "price_basis": ["market", "manual"]})
    fx = {"CAD": pf.FxRate(0.75, date(2026, 10, 9), "manual")}
    pos = pf.value_positions(h, prices, fx, as_of=date(2026, 10, 11)).set_index("id")

    assert pos.loc[1, "market_value_usd"] == pytest.approx(1100.0)
    assert pos.loc[1, "cost_basis_usd"] == pytest.approx(1000.0)
    # CAD lot: price unchanged in CAD, so all of the gain is FX: cost 10*100*0.70 = 700, value 10*100*0.75 = 750
    assert pos.loc[2, "cost_basis_usd"] == pytest.approx(700.0)
    assert pos.loc[2, "market_value_usd"] == pytest.approx(750.0)
    assert pos.loc[2, "unrealized_pnl_usd"] == pytest.approx(50.0)
    assert pos.loc[2, "unrealized_pnl_pct"] == pytest.approx(50.0 / 700.0)
    assert pos["weight"].sum() == pytest.approx(1.0)
    assert pos.loc[1, "weight"] == pytest.approx(1100.0 / 1850.0)
    assert list(pos["status"]) == ["ok", "ok"]
    assert pos.loc[1, "price_age_days"] == 2 and pos.loc[2, "price_age_days"] == 10


def test_position_without_an_fx_rate_is_flagged_not_valued_at_zero_or_a_guess():
    h = holdings(lot(1, "AAPL"), lot(2, "FUND", currency="CAD", source="manual", fx=0.7))
    prices = pd.DataFrame({"id": [1, 2], "price_local": [110.0, 100.0],
                           "price_date": [date(2026, 10, 9)] * 2, "price_basis": ["market", "manual"]})
    pos = pf.value_positions(h, prices, {"CAD": None}, as_of=date(2026, 10, 11)).set_index("id")
    assert np.isnan(pos.loc[2, "market_value_usd"]) and pos.loc[2, "status"] == "no CAD FX rate"
    assert pos.loc[1, "weight"] == pytest.approx(1.0)       # weights are over valued positions only
    totals = pf.portfolio_totals(pos.reset_index())
    assert totals["n_unvalued"] == 1 and totals["total_value_usd"] == pytest.approx(1100.0)
    assert totals["total_cost_usd"] == pytest.approx(1000.0)   # the unvalued lot is out of both sides of P&L
    assert totals["unrealized_pnl_pct"] == pytest.approx(0.1)


def test_missing_price_and_cost_fallback_statuses():
    h = holdings(lot(1, "NOPE"), lot(2, "NEW", source="manual"))
    prices = pd.DataFrame({"id": [1, 2], "price_local": [np.nan, 100.0], "price_date": [None, date(2026, 1, 5)],
                           "price_basis": ["missing", "cost"]})
    pos = pf.value_positions(h, prices, {}, as_of=date(2026, 10, 11)).set_index("id")
    assert pos.loc[1, "status"] == "no price data" and np.isnan(pos.loc[1, "market_value_usd"])
    assert pos.loc[2, "status"] == "at cost (no manual price yet)"
    assert pos.loc[2, "market_value_usd"] == pytest.approx(1000.0)


def test_empty_portfolio_valuation():
    pos = pf.value_positions(pd.DataFrame(columns=pf.HOLDING_COLUMNS), pd.DataFrame(), {}, date(2026, 10, 11))
    assert pos.empty and list(pos.columns) == pf.POSITION_COLUMNS
    assert pf.portfolio_totals(pos)["n_positions"] == 0
    assert pf.allocation(pos, "sector").empty


def test_allocation_buckets_blank_sectors_and_sums_to_one():
    pos = pd.DataFrame({
        "sector": ["Technology", None, "", "Technology"], "asset_class": ["stock", "fund", "fund", "stock"],
        "market_value_usd": [600.0, 100.0, 100.0, np.nan],
    })
    by_sector = pf.allocation(pos, "sector").set_index("label")
    assert by_sector.loc["Technology", "market_value_usd"] == 600.0    # NaN lot excluded
    assert by_sector.loc["Unclassified", "market_value_usd"] == 200.0
    assert by_sector["weight"].sum() == pytest.approx(1.0)
    assert pf.allocation(pos, "sector")["label"].tolist() == ["Technology", "Unclassified"]   # largest first


# ---------------------------------------------------------------------------
# USD price panel
# ---------------------------------------------------------------------------

def _panel(h, auto=None, manual=None, fx=None, manual_fx_rates=None):
    return pf.build_usd_price_panel(h, auto, manual if manual is not None else NO_MANUAL_PRICES, fx or {},
                                    manual_fx_rates if manual_fx_rates is not None else NO_MANUAL_FX)


def test_panel_starts_at_cost_on_the_purchase_date_and_is_nan_before():
    h = holdings(lot(1, "A", purchase=date(2026, 1, 5), price=100.0), lot(2, "B", purchase=date(2026, 1, 7), price=50.0))
    auto = pd.concat([
        closes("A", pd.bdate_range("2026-01-05", "2026-01-09"), [999.0, 102, 104, 103, 105]),   # the 01-05 close is ignored
        closes("B", ["2026-01-08", "2026-01-09"], [51.0, 52.0]),
    ])
    panel = _panel(h, auto)
    assert list(panel.index) == list(pd.bdate_range("2026-01-05", "2026-01-09"))
    assert panel[1].tolist() == [100.0, 102.0, 104.0, 103.0, 105.0]     # purchase price, not that day's close
    assert np.isnan(panel[2].iloc[0]) and np.isnan(panel[2].iloc[1])      # before purchase
    assert panel[2].tolist()[2:] == [50.0, 51.0, 52.0]


def test_manual_position_is_flat_between_marks():
    h = holdings(lot(1, "FUND", source="manual", price=100.0))
    marks = manual_prices([("FUND", date(2026, 1, 7), 110.0, "USD"), ("FUND", date(2026, 1, 2), 5.0, "USD")])
    panel = _panel(h, manual=marks)
    assert panel[1].tolist() == [100.0, 100.0, 110.0]      # the pre-purchase mark is ignored


def test_cad_position_follows_the_fx_path_from_its_purchase_rate():
    h = holdings(lot(1, "FUND", currency="CAD", source="manual", price=100.0, fx=0.70))
    marks = manual_prices([("FUND", date(2026, 1, 7), 100.0, "CAD")])
    pipeline = {"CAD": fx_series(["2026-01-02", "2026-01-06", "2026-01-07"], [0.60, 0.71, 0.72])}
    panel = _panel(h, manual=marks, fx=pipeline)
    # 01-02 is before the purchase, so the purchase-date rate (0.70) applies on 01-05, then the series
    assert panel[1].tolist() == pytest.approx([70.0, 71.0, 72.0])


def test_a_manual_fx_rate_overrides_the_pipeline_on_the_same_date():
    h = holdings(lot(1, "FUND", currency="CAD", source="manual", price=100.0, fx=0.70))
    marks = manual_prices([("FUND", date(2026, 1, 7), 100.0, "CAD")])
    pipeline = {"CAD": fx_series(["2026-01-07"], [0.72])}
    panel = _panel(h, manual=marks, fx=pipeline, manual_fx_rates=manual_fx([("CAD", date(2026, 1, 7), 0.80)]))
    assert panel[1].iloc[-1] == pytest.approx(80.0)


def test_non_usd_lot_with_no_fx_at_all_is_all_nan_not_frozen_at_the_purchase_rate():
    h = holdings(lot(1, "FUND", currency="CAD", source="manual", price=100.0, fx=0.70))
    marks = manual_prices([("FUND", date(2026, 1, 7), 100.0, "CAD")])
    assert _panel(h, manual=marks)[1].isna().all()


def test_weekend_purchase_appears_on_the_next_business_day():
    h = holdings(lot(1, "FUND", source="manual", price=100.0, purchase=date(2026, 1, 10)))   # a Saturday
    panel = _panel(h)
    assert list(panel.index) == [pd.Timestamp("2026-01-12")] and panel[1].iloc[0] == 100.0


def test_empty_holdings_give_an_empty_panel():
    assert _panel(pd.DataFrame(columns=pf.HOLDING_COLUMNS)).empty


# ---------------------------------------------------------------------------
# Time-weighted return
# ---------------------------------------------------------------------------

def _two_lot_panel():
    """A: 10 sh bought 01-05 at 100. B: 10 sh bought 01-07 at 100 (doubling the money in)."""
    h = holdings(lot(1, "A", purchase=date(2026, 1, 5)), lot(2, "B", purchase=date(2026, 1, 7)))
    auto = pd.concat([
        closes("A", pd.bdate_range("2026-01-06", "2026-01-09"), [110.0, 110.0, 121.0, 121.0]),
        closes("B", ["2026-01-08", "2026-01-09"], [100.0, 120.0]),
    ])
    panel = _panel(h, auto)
    return h, panel, h.set_index("id")["shares"].astype(float)


def test_time_weighted_return_ignores_new_money():
    _, panel, shares = _two_lot_panel()
    r = pf.portfolio_returns(panel, shares)
    assert r.loc["2026-01-06"] == pytest.approx(0.10)
    assert r.loc["2026-01-07"] == pytest.approx(0.0)           # B bought at cost: $1000 in, 0% return
    assert r.loc["2026-01-08"] == pytest.approx(110 / 2100)    # A +10% on 1100, B flat on 1000
    assert r.loc["2026-01-09"] == pytest.approx(200 / 2210)    # A flat on 1210, B +20% on 1000
    twr = (1 + r).prod() - 1
    assert twr == pytest.approx(1.1 * (1 + 110 / 2100) * (1 + 200 / 2210) - 1)
    # A naive end-value / money-in return (2410 / 2000 - 1 = 20.5%) would understate it: the second lot
    # sat flat for a day and wasn't exposed to A's early gains.
    assert twr > 0.2


def test_returns_of_an_empty_panel():
    assert pf.portfolio_returns(pd.DataFrame(), pd.Series(dtype=float)).empty


def test_trading_day_restriction_drops_market_holidays_only_inside_the_covered_range():
    idx = pd.bdate_range("2026-01-14", "2026-01-23")
    panel = pd.DataFrame({1: np.arange(len(idx), dtype=float) + 100}, index=idx)
    trading = pd.DatetimeIndex([d for d in idx if d != pd.Timestamp("2026-01-19")][2:])   # starts 01-16; no 01-19
    out = pf.restrict_to_trading_days(panel, trading)
    assert pd.Timestamp("2026-01-19") not in out.index          # holiday inside the covered range: dropped
    assert pd.Timestamp("2026-01-14") in out.index              # before the benchmark's range: kept
    assert pf.restrict_to_trading_days(panel, None).equals(panel)


# ---------------------------------------------------------------------------
# Risk / return stats
# ---------------------------------------------------------------------------

def _returns(values, start="2026-01-05"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_beta_of_a_series_that_is_twice_the_benchmark_is_two():
    bench = _returns(np.sin(np.arange(100)) * 0.01)
    stats = pf.risk_return_stats(2 * bench, bench, risk_free_rate=0.0)
    assert stats["beta"] == pytest.approx(2.0)
    assert stats["beta_n_obs"] == 100 and stats["n_obs"] == 100


def test_stats_need_enough_observations():
    r = _returns([0.01] * 10)
    stats = pf.risk_return_stats(r, r, 0.04)
    assert stats["twr_total"] == pytest.approx(1.01 ** 10 - 1)
    assert stats["twr_annualized"] is None and stats["volatility"] is None
    assert stats["sharpe"] is None and stats["beta"] is None
    assert stats["beta_n_obs"] == 10


def test_annualised_return_only_from_enough_history():
    assert pf.risk_return_stats(_returns([0.0004] * 59))["twr_annualized"] is None
    year = pf.risk_return_stats(_returns([0.0004] * 252))
    assert year["twr_annualized"] == pytest.approx(year["twr_total"])


def test_sharpe_uses_the_excess_over_the_risk_free_rate():
    r = _returns(np.tile([0.012, -0.004], 30))
    low = pf.risk_return_stats(r, None, risk_free_rate=0.0)
    high = pf.risk_return_stats(r, None, risk_free_rate=2.0)      # 200% a year: far above the mean daily return
    expected = (r.mean() / r.std(ddof=1)) * np.sqrt(252)
    assert low["sharpe"] == pytest.approx(expected)
    assert low["volatility"] == pytest.approx(r.std(ddof=1) * np.sqrt(252))
    assert high["sharpe"] < 0 < low["sharpe"]
    assert pf.risk_return_stats(r, None, None)["sharpe"] is None   # no risk-free rate: no Sharpe


def test_zero_volatility_gives_no_sharpe_instead_of_dividing_by_zero():
    stats = pf.risk_return_stats(_returns([0.0] * 30), None, 0.04)      # e.g. only manual positions, none re-priced
    assert stats["volatility"] == 0.0 and stats["sharpe"] is None


def test_max_drawdown_is_peak_to_trough():
    stats = pf.risk_return_stats(_returns([0.10, -0.20, 0.05]))
    assert stats["max_drawdown"] == pytest.approx(0.88 / 1.1 - 1)


def test_stats_of_nothing():
    stats = pf.risk_return_stats(pd.Series(dtype=float), None, 0.04)
    assert stats["n_obs"] == 0 and stats["twr_total"] is None and stats["start"] is None


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

def _price_panel(n=40):
    idx = pd.bdate_range("2026-01-05", periods=n)
    base = 100 * np.cumprod(1 + 0.01 * np.sin(np.arange(n) * 1.3))
    return pd.DataFrame({1: base, 2: base * 2.0, 3: np.full(n, 50.0), 4: 100 * np.cumprod(1 + 0.01 * np.cos(np.arange(n)))},
                        index=idx)


def test_correlation_drops_zero_variance_series_instead_of_returning_nan():
    """Regression: a flat price series has undefined correlation (std 0) and must not poison the matrix."""
    corr = pf.correlation_matrix(_price_panel(), {1: "A", 2: "B", 3: "FLAT", 4: "C"}, [1, 2, 3, 4])
    assert list(corr.columns) == ["A", "B", "C"]
    assert not corr.isna().any().any()
    assert corr.loc["A", "B"] == pytest.approx(1.0)      # B is just A scaled
    assert corr.loc["A", "C"] == pytest.approx(corr.loc["C", "A"])


def test_correlation_only_uses_eligible_lots():
    corr = pf.correlation_matrix(_price_panel(), {1: "A", 2: "B", 3: "FLAT", 4: "C"}, [1, 4])
    assert list(corr.columns) == ["A", "C"]


def test_correlation_needs_two_series_and_enough_days():
    panel = _price_panel()
    assert pf.correlation_matrix(panel, {1: "A", 2: "B"}, [1]).empty
    assert pf.correlation_matrix(panel.iloc[:10], {1: "A", 2: "B"}, [1, 2]).empty    # < 20 returns


def test_lots_of_the_same_ticker_appear_once():
    corr = pf.correlation_matrix(_price_panel(), {1: "A", 2: "A", 4: "C"}, [1, 2, 4])
    assert list(corr.columns) == ["A", "C"]


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

def _end_to_end_inputs(with_fx: bool):
    days = pd.bdate_range("2026-01-05", periods=45)
    rng = np.random.default_rng(7)
    aaa = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, len(days)))
    spy = 400 * np.cumprod(1 + rng.normal(0.001, 0.008, len(days)))
    h = holdings(
        lot(1, "AAA", purchase=date(2026, 1, 5), price=100.0),
        lot(2, "FUND", currency="CAD", source="manual", price=50.0, fx=0.70, asset_class="fund", sector=None,
            purchase=date(2026, 1, 12)),
    )
    auto = closes("AAA", days, aaa)
    bench = closes("SPY", days, spy)
    marks = manual_prices([("FUND", date(2026, 2, 2), 52.0, "CAD"), ("FUND", date(2026, 3, 2), 55.0, "CAD")])
    fx = {"CAD": fx_series(days, np.linspace(0.70, 0.74, len(days)))} if with_fx else {}
    return h, auto, marks, fx, bench


def test_analyze_portfolio_end_to_end():
    h, auto, marks, fx, bench = _end_to_end_inputs(with_fx=True)
    result = pf.analyze_portfolio(h, auto, marks, fx, NO_MANUAL_FX, bench, risk_free_rate=0.04)

    assert result.includes_manual and result.excluded_labels == []
    assert result.stats["n_obs"] > 20 and result.stats["beta"] is not None and result.stats["sharpe"] is not None
    assert result.correlation.empty          # only one market-priced lot: nothing to correlate
    assert result.value_history.index.is_monotonic_increasing
    # cost basis steps up when the CAD lot is bought: 10*100 + 10*50*0.70
    assert result.cost_history.iloc[0] == pytest.approx(1000.0)
    assert result.cost_history.iloc[-1] == pytest.approx(1000.0 + 350.0)
    # the last value matches the pieces: AAA at its last close + FUND at its last mark and last FX
    last_fx = fx["CAD"]["rate"].iloc[-1]
    expected = 10 * auto["close_price"].iloc[-1] + 10 * 55.0 * last_fx
    assert result.value_history.iloc[-1] == pytest.approx(expected)


def test_analyze_portfolio_excludes_lots_it_cannot_put_in_usd():
    h, auto, marks, fx, bench = _end_to_end_inputs(with_fx=False)
    result = pf.analyze_portfolio(h, auto, marks, fx, NO_MANUAL_FX, bench, risk_free_rate=0.04)
    assert result.excluded_labels == ["FUND"]
    assert not result.includes_manual
    assert result.value_history.iloc[-1] == pytest.approx(10 * auto["close_price"].iloc[-1])


def test_analyze_portfolio_without_a_benchmark_still_returns_everything_but_beta():
    h, auto, marks, fx, _ = _end_to_end_inputs(with_fx=True)
    result = pf.analyze_portfolio(h, auto, marks, fx, NO_MANUAL_FX, None, risk_free_rate=None)
    assert result.stats["beta"] is None and result.stats["sharpe"] is None and result.stats["twr_total"] is not None


def test_analyze_empty_portfolio():
    result = pf.analyze_portfolio(pd.DataFrame(columns=pf.HOLDING_COLUMNS), None, None, {}, None, None, 0.04)
    assert result.value_history.empty and result.stats["n_obs"] == 0


# ---------------------------------------------------------------------------
# Dividends received
# ---------------------------------------------------------------------------

def dividends(*rows) -> pd.DataFrame:
    """rows: (id, ticker, pay_date, amount, currency, fx_rate)"""
    return pd.DataFrame(list(rows), columns=pf.DIVIDEND_COLUMNS)


HELD = {"AAA": ("USD", date(2026, 1, 5)), "FUND": ("CAD", date(2026, 1, 5))}


def validate_div(**overrides):
    base = dict(ticker="aaa", pay_date="2026-03-02", amount=25, fx_rate=None, held=HELD,
                pipeline_fx=None, manual_fx=None, today=TODAY)
    return pf.validate_new_dividend(**{**base, **overrides})


def test_valid_usd_dividend_is_normalised():
    record, error = validate_div()
    assert error is None
    assert record == {"ticker": "AAA", "pay_date": date(2026, 3, 2), "amount": 25.0, "currency": "USD", "fx_rate": 1.0}


def test_cad_dividend_takes_the_typed_rate_else_the_stored_one_else_is_rejected():
    typed, _ = validate_div(ticker="FUND", fx_rate=0.71)
    assert typed["currency"] == "CAD" and typed["fx_rate"] == 0.71
    stored, _ = validate_div(ticker="FUND", pipeline_fx=fx_series(["2026-02-27", "2026-03-04"], [0.72, 0.75]))
    assert stored["fx_rate"] == 0.72                          # latest on or before the 2026-03-02 pay date
    record, error = validate_div(ticker="FUND")
    assert record is None and "No CAD->USD rate" in error


@pytest.mark.parametrize("overrides,fragment", [
    (dict(ticker=""), "Choose a position"),
    (dict(ticker="ZZZ"), "Choose a position"),
    (dict(amount=0), "positive number"),
    (dict(amount="abc"), "positive number"),
    (dict(pay_date="nonsense"), "valid pay date"),
    (dict(pay_date="2026-12-31"), "future"),
    (dict(pay_date="2026-01-05"), "after you bought"),
    (dict(ticker="FUND", fx_rate=-1), "positive number"),
])
def test_invalid_dividends_are_rejected_with_a_reason(overrides, fragment):
    record, error = validate_div(**overrides)
    assert record is None and fragment in error


def test_totals_add_income_to_value_and_return_but_not_to_cost_or_unrealized():
    h = holdings(lot(1, "AAA", shares=10, price=100.0))
    prices = pf.latest_position_prices(h, closes("AAA", ["2026-02-02"], [110.0]), NO_MANUAL_PRICES)
    positions = pf.value_positions(h, prices, {}, date(2026, 2, 3))
    totals = pf.portfolio_totals(positions, dividends((1, "AAA", date(2026, 1, 20), 30.0, "USD", 1.0)))
    assert totals["total_value_usd"] == pytest.approx(1100.0)
    assert totals["income_usd"] == pytest.approx(30.0)
    assert totals["total_value_with_income_usd"] == pytest.approx(1130.0)
    assert totals["unrealized_pnl_usd"] == pytest.approx(100.0)
    assert totals["total_return_usd"] == pytest.approx(130.0)
    assert totals["total_return_pct"] == pytest.approx(0.13)
    assert totals["total_cost_usd"] == pytest.approx(1000.0)


def test_cad_income_is_converted_at_its_pay_date_rate_and_unvalued_tickers_are_left_out():
    h = holdings(lot(1, "AAA"), lot(2, "NOPX"))               # NOPX has no price data -> not valued
    prices = pf.latest_position_prices(h, closes("AAA", ["2026-02-02"], [100.0]), NO_MANUAL_PRICES)
    positions = pf.value_positions(h, prices, {}, date(2026, 2, 3))
    divs = dividends((1, "AAA", date(2026, 1, 20), 40.0, "CAD", 0.75), (2, "NOPX", date(2026, 1, 20), 99.0, "USD", 1.0))
    totals = pf.portfolio_totals(positions, divs)
    assert totals["income_usd"] == pytest.approx(30.0)        # 40 CAD x 0.75; NOPX excluded like its P&L


def test_totals_without_dividends_have_zero_income():
    h = holdings(lot(1, "AAA"))
    prices = pf.latest_position_prices(h, closes("AAA", ["2026-02-02"], [100.0]), NO_MANUAL_PRICES)
    totals = pf.portfolio_totals(pf.value_positions(h, prices, {}, date(2026, 2, 3)))
    assert totals["income_usd"] == 0.0 and totals["total_return_usd"] == pytest.approx(totals["unrealized_pnl_usd"])
    assert pf.portfolio_totals(pd.DataFrame(columns=pf.POSITION_COLUMNS))["income_usd"] == 0.0


def test_a_dividend_is_a_return_on_its_pay_date_not_new_money():
    # One lot, flat price 100 for 10 sh ($1,000). A $50 dividend on 01-08 is +5% that day, then nothing.
    h = holdings(lot(1, "AAA", shares=10, price=100.0))
    auto = closes("AAA", pd.bdate_range("2026-01-06", "2026-01-12"), [100.0] * 5)
    panel = _panel(h, auto)
    shares = h.set_index("id")["shares"].astype(float)
    income = pf.income_by_lot(dividends((1, "AAA", date(2026, 1, 8), 50.0, "USD", 1.0)), h, [1], panel.index)
    r = pf.portfolio_returns(panel, shares, income)
    assert r.loc["2026-01-08"] == pytest.approx(0.05)
    assert r.drop(pd.Timestamp("2026-01-08")).abs().max() == pytest.approx(0.0)
    assert (pf.portfolio_returns(panel, shares) == 0).all()   # price-only: nothing happened


def test_income_is_shared_across_lots_held_before_the_pay_date_by_shares():
    h = holdings(lot(1, "AAA", shares=10, purchase=date(2026, 1, 5)), lot(2, "AAA", shares=30, purchase=date(2026, 1, 5)),
                 lot(3, "AAA", shares=60, purchase=date(2026, 2, 2)))      # lot 3 is bought after the dividend
    grid = pd.bdate_range("2026-01-05", "2026-02-13")
    income = pf.income_by_lot(dividends((1, "AAA", date(2026, 1, 20), 80.0, "USD", 1.0)), h, [1, 2, 3], grid)
    on_day = income.loc["2026-01-20"]
    assert on_day[1] == pytest.approx(20.0) and on_day[2] == pytest.approx(60.0) and on_day[3] == 0.0
    assert income.to_numpy().sum() == pytest.approx(80.0)


def test_a_weekend_dividend_lands_on_the_next_business_day():
    h = holdings(lot(1, "AAA"))
    grid = pd.bdate_range("2026-01-05", "2026-01-16")
    income = pf.income_by_lot(dividends((1, "AAA", date(2026, 1, 10), 10.0, "USD", 1.0)), h, [1], grid)   # a Saturday
    assert income[1].loc["2026-01-12"] == pytest.approx(10.0) and income[1].sum() == pytest.approx(10.0)


def test_analyze_with_dividends_adds_income_to_total_value_and_total_return_but_not_price_return():
    h, auto, marks, fx, bench = _end_to_end_inputs(with_fx=True)
    plain = pf.analyze_portfolio(h, auto, marks, fx, NO_MANUAL_FX, bench, risk_free_rate=0.04)
    divs = dividends((1, "AAA", date(2026, 2, 16), 40.0, "USD", 1.0),
                     (2, "FUND", date(2026, 3, 2), 100.0, "CAD", 0.73))       # FUND bought 01-12, so eligible
    with_div = pf.analyze_portfolio(h, auto, marks, fx, NO_MANUAL_FX, bench, risk_free_rate=0.04, dividends=divs)

    assert not plain.has_income and with_div.has_income
    assert with_div.value_history.equals(plain.value_history)                   # market value is untouched
    gap = with_div.total_value_history - with_div.value_history
    assert gap.iloc[-1] == pytest.approx(40.0 + 73.0)
    assert gap.loc["2026-02-13"] == pytest.approx(0.0) and gap.loc["2026-02-16"] == pytest.approx(40.0)
    assert with_div.stats["twr_total"] > plain.stats["twr_total"]               # headline is total return now
    assert with_div.stats["twr_price_total"] == pytest.approx(plain.stats["twr_total"])
    assert "twr_price_total" not in plain.stats


def test_dividends_for_excluded_or_unheld_tickers_do_not_create_income():
    h, auto, marks, fx, bench = _end_to_end_inputs(with_fx=False)               # the CAD FUND lot has no FX -> excluded
    divs = dividends((1, "FUND", date(2026, 3, 2), 100.0, "CAD", 0.73), (2, "GONE", date(2026, 3, 2), 5.0, "USD", 1.0))
    result = pf.analyze_portfolio(h, auto, marks, fx, NO_MANUAL_FX, bench, risk_free_rate=0.04, dividends=divs)
    assert not result.has_income and result.excluded_labels == ["FUND"]
