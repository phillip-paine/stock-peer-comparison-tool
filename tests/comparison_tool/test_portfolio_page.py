"""Page-level tests for the Portfolio page. Callbacks run through a real
`dash.Dash` app against the real in-memory DB (the `session` fixture), so
what's tested is the same path the dashboard takes: form -> validation ->
PortfolioRepository -> transforms -> rendered components."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import pytest

from src.peer_comparison_tool.comparison_tool import portfolio_page as page
from peer_comparison_tool.data.models import AssetClassTimeSeries, CompanyInfo, TickerTimeSeries
from peer_comparison_tool.data.portfolio_repository import PortfolioRepository

TODAY = date(2026, 10, 11)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(session, monkeypatch):
    monkeypatch.setattr(page, "_today", lambda: TODAY)

    @contextmanager
    def scope():
        yield session
        session.commit()      # what the real session_scope does on success

    dash_app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY], suppress_callback_exceptions=True)
    dash_app.layout = page.get_portfolio_page_layout()
    page.register_portfolio_callback(dash_app, scope)
    return dash_app


@pytest.fixture()
def repo(session):
    return PortfolioRepository(session)


def _callback(app, fragment: str):
    for key, cb in app.callback_map.items():
        if fragment in key:
            return cb["callback"].__wrapped__
    raise AssertionError(f"no callback for {fragment}")


def _render(app):
    """The render callback's ten outputs, as a dict."""
    out = _callback(app, "pf-holdings-content.children")(0, 0, 0, 0, 0, 0)
    keys = ["holdings", "alloc_class", "alloc_sector", "stats", "corr", "history", "price_options", "fx_status",
            "dividends", "div_options"]
    return dict(zip(keys, out))


def _walk(component):
    if component is None or isinstance(component, (str, int, float)):
        return
    if isinstance(component, (list, tuple)):
        for c in component:
            yield from _walk(c)
        return
    yield component
    yield from _walk(getattr(component, "children", None))


def _tables(component):
    return [c for c in _walk(component) if c.__class__.__name__ == "DataTable"]


def _graphs(component):
    return [c for c in _walk(component) if c.__class__.__name__ == "Graph"]


def _flatten_text(component) -> str:
    if component is None:
        return ""
    if isinstance(component, str):
        return component
    if isinstance(component, (list, tuple)):
        return " ".join(_flatten_text(c) for c in component)
    data = getattr(component, "data", None)
    parts = [" ".join(str(v) for r in data for v in r.values()) if isinstance(data, list) and data else ""]
    parts.append(_flatten_text(getattr(component, "children", None)))
    return " ".join(parts)


def _holding(repo, ticker, **overrides):
    fields = dict(ticker=ticker, name=None, asset_class="stock", sector=None, currency="USD", price_source="auto",
                  shares=10.0, purchase_price=100.0, purchase_date=date(2026, 1, 5), purchase_fx_rate=1.0)
    fields.update(overrides)
    return repo.add_holding(**fields)


def _stock(session, repo, ticker, dates, closes, name=None, sector="Technology"):
    session.add(CompanyInfo(ticker=ticker, name=name or f"{ticker} Inc.", sector=sector))
    session.flush()
    repo.upsert_dataframe(TickerTimeSeries, pd.DataFrame({"ticker": ticker, "date": dates, "close_price": closes}))


def _asset(repo, name, dates, values):
    repo.upsert_dataframe(AssetClassTimeSeries, pd.DataFrame({"ticker": name, "date": dates, "close_price": values}))


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def test_layout_sections_are_in_the_agreed_order(app):
    ids = [c.id for c in _walk(page.get_portfolio_page_layout()) if getattr(c, "id", None)]
    order = ["pf-add-button", "pf-price-button", "pf-fx-button", "pf-holdings-content", "pf-div-button",
             "pf-dividends-content", "pf-alloc-class",
             "pf-alloc-sector", "pf-stats-content", "pf-corr-content", "pf-history-content"]
    assert [i for i in ids if i in order] == order
    assert "back-to-home" in ids


def test_add_form_covers_the_agreed_fields(app):
    ids = {c.id for c in _walk(page.get_portfolio_page_layout()) if getattr(c, "id", None)}
    assert {"pf-ticker", "pf-shares", "pf-purchase-price", "pf-purchase-date", "pf-currency", "pf-source",
            "pf-purchase-fx", "pf-price-ticker", "pf-fx-rate", "pf-fx-currency"} <= ids


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

def test_empty_portfolio_renders_every_section_with_a_message(app):
    r = _render(app)
    assert "No positions yet" in _flatten_text(r["holdings"])
    assert "Nothing to show" in _flatten_text(r["alloc_class"]) and "Nothing to show" in _flatten_text(r["alloc_sector"])
    assert "Add a position" in _flatten_text(r["stats"])
    assert "Needs at least two" in _flatten_text(r["corr"])
    assert "Add a position" in _flatten_text(r["history"])
    assert r["price_options"] == []
    assert "no rate available" in r["fx_status"]       # and says how to fix it


# ---------------------------------------------------------------------------
# Adding positions
# ---------------------------------------------------------------------------

ADD_ARGS = dict(n_clicks=1, ticker="aapl", name=None, asset_class="stock", sector=None, source="auto",
                currency="USD", shares=10, purchase_price=150.0, purchase_date="2026-03-02", purchase_fx=None,
                counter=0)


def _add(app, **overrides):
    args = {**ADD_ARGS, **overrides}
    return _callback(app, "pf-add-message.children")(*args.values())


def test_adding_an_auto_priced_stock_prefills_name_and_sector_from_company_info(app, session, repo):
    _stock(session, repo, "AAPL", [date(2026, 10, 9)], [205.0], name="Apple Inc.", sector="Technology")
    message, counter = _add(app)
    assert "Added AAPL" in _flatten_text(message) and counter == 1
    row = repo.list_holdings().iloc[0]
    assert (row["ticker"], row["name"], row["sector"], row["currency"]) == ("AAPL", "Apple Inc.", "Technology", "USD")
    assert row["purchase_fx_rate"] == 1.0 and row["purchase_date"] == date(2026, 3, 2)


def test_an_auto_priced_ticker_with_no_stored_history_is_rejected(app, repo):
    message, counter = _add(app, ticker="ZZZZ")
    assert "No stored price history" in _flatten_text(message)
    assert counter is dash.no_update and repo.list_holdings().empty


def test_a_cad_position_with_no_fx_rate_is_rejected_not_saved_with_a_guess(app, repo):
    message, counter = _add(app, ticker="FUND", source="manual", currency="CAD")
    assert "No CAD->USD rate" in _flatten_text(message)
    assert counter is dash.no_update and repo.list_holdings().empty


def test_a_cad_position_picks_up_the_stored_rate_for_its_purchase_date(app, repo):
    _asset(repo, "CADUSD_fx", [date(2026, 2, 27), date(2026, 3, 3)], [0.70, 0.71])
    _add(app, ticker="FUND", source="manual", currency="CAD", asset_class="fund", purchase_price=50.0)
    row = repo.list_holdings().iloc[0]
    assert row["currency"] == "CAD" and row["purchase_fx_rate"] == pytest.approx(0.70)


def test_a_typed_purchase_fx_rate_wins_for_a_cad_position(app, repo):
    _add(app, ticker="FUND", source="manual", currency="CAD", purchase_fx=0.7421)
    assert repo.list_holdings().iloc[0]["purchase_fx_rate"] == pytest.approx(0.7421)


def test_bad_form_input_gives_a_message_and_no_refresh(app, repo):
    for overrides in ({"shares": -1}, {"purchase_price": None}, {"purchase_date": "2026-10-12"}, {"ticker": ""}):
        message, counter = _add(app, source="manual", **overrides)
        assert _flatten_text(message) and counter is dash.no_update
    assert repo.list_holdings().empty


# ---------------------------------------------------------------------------
# Valuation, allocation: the CAD-hedged-fund case
# ---------------------------------------------------------------------------

@pytest.fixture()
def mixed_portfolio(session, repo):
    """10 AAPL (bought at $100, now $110) + 10 units of a manually priced CAD fund (bought at C$100 when CAD
    was 0.70; last marked C$100 on 10-01; CAD now 0.75 by manual override)."""
    _stock(session, repo, "AAPL", [date(2026, 10, 8), date(2026, 10, 9)], [108.0, 110.0], sector="Technology")
    _holding(repo, "AAPL", name="Apple Inc.", sector="Technology")
    _holding(repo, "FUND", name="CAD Hedged Fund", asset_class="fund", currency="CAD", price_source="manual",
             purchase_price=100.0, purchase_fx_rate=0.70)
    repo.upsert_manual_price("FUND", date(2026, 10, 1), 100.0, "CAD")
    repo.upsert_manual_fx_rate("CAD", date(2026, 10, 9), 0.75)
    session.commit()


def test_holdings_table_shows_usd_values_and_the_fx_driven_gain(app, mixed_portfolio):
    r = _render(app)
    [table] = _tables(r["holdings"])
    rows = {row["ticker"]: row for row in table.data}

    assert rows["AAPL"]["value"] == "$1,100.00" and rows["AAPL"]["pnl"] == "+$100.00"
    # CAD fund: price unchanged in CAD, so the whole gain is the currency: cost 10*100*0.70, value 10*100*0.75
    assert rows["FUND"]["value"] == "$750.00" and rows["FUND"]["cost"] == "$700.00"
    assert rows["FUND"]["pnl"] == "+$50.00" and rows["FUND"]["fx"] == "0.7500" and rows["FUND"]["currency"] == "CAD"
    assert rows["AAPL"]["weight"] == "59.5%" and rows["FUND"]["weight"] == "40.5%"
    assert rows["FUND"]["name"] == "CAD Hedged Fund" and rows["FUND"]["source"] == "manual"

    text = _flatten_text(r["holdings"])
    assert "$1,850.00" in text                                  # total value
    assert "Manual prices older than 7 days: FUND" in text      # marked 10 days before TODAY
    assert table.row_selectable == "multi"
    assert getattr(table, "sort_action", None) in (None, "none")     # selection indexes `data` directly
    assert all("id" in row for row in table.data)               # needed to map selections to lots


def test_fx_status_and_manual_price_options(app, mixed_portfolio):
    r = _render(app)
    assert "CAD->USD: 0.7500 (manual, as of 2026-10-09)" in r["fx_status"]
    assert r["price_options"] == [{"label": "FUND (CAD)", "value": "FUND"}]


def test_allocation_pies_use_usd_value_by_class_and_sector(app, mixed_portfolio):
    r = _render(app)
    [by_class] = _graphs(r["alloc_class"])
    pie = by_class.figure.data[0]
    assert dict(zip(pie.labels, pie.values)) == {"stock": pytest.approx(1100.0), "fund": pytest.approx(750.0)}
    [by_sector] = _graphs(r["alloc_sector"])
    sector = dict(zip(by_sector.figure.data[0].labels, by_sector.figure.data[0].values))
    assert sector == {"Technology": pytest.approx(1100.0), "Unclassified": pytest.approx(750.0)}


def test_a_new_manual_price_changes_the_value(app, session, repo, mixed_portfolio):
    save = _callback(app, "pf-price-message.children")
    message, counter = save(1, "FUND", 110.0, "2026-10-10", 0)
    assert "Saved FUND" in _flatten_text(message) and counter == 1

    [table] = _tables(_render(app)["holdings"])
    fund = next(r for r in table.data if r["ticker"] == "FUND")
    assert fund["value"] == "$825.00" and fund["price"] == "110.00" and fund["price_date"] == "2026-10-10"
    assert "Manual prices older" not in _flatten_text(_render(app)["holdings"])


def test_manual_price_rejects_unknown_positions_and_bad_values(app, mixed_portfolio, repo):
    save = _callback(app, "pf-price-message.children")
    for args in ((1, "AAPL", 110.0, "2026-10-10", 0),      # auto-priced: has no manual price
                 (1, "FUND", -5, "2026-10-10", 0),
                 (1, "FUND", 110.0, "2026-10-12", 0),     # future
                 (1, None, 110.0, "2026-10-10", 0)):
        message, counter = save(*args)
        assert _flatten_text(message) and counter is dash.no_update
    assert len(repo.manual_prices()) == 1


def test_a_manual_fx_rate_flows_through_to_values(app, mixed_portfolio):
    save = _callback(app, "pf-fx-message.children")
    message, counter = save(1, "CAD", 0.80, "2026-10-10", 0)
    assert "Saved CAD->USD 0.8000" in _flatten_text(message) and counter == 1

    r = _render(app)
    fund = next(row for row in _tables(r["holdings"])[0].data if row["ticker"] == "FUND")
    assert fund["value"] == "$800.00"                              # 10 * C$100 * 0.80
    assert "0.8000 (manual, as of 2026-10-10)" in r["fx_status"]


def test_manual_fx_rejects_bad_input(app):
    save = _callback(app, "pf-fx-message.children")
    for args in ((1, "CAD", 0, "2026-10-10", 0), (1, "USD", 1.0, "2026-10-10", 0), (1, "CAD", 0.7, "2026-10-12", 0)):
        message, counter = save(*args)
        assert _flatten_text(message) and counter is dash.no_update


def test_a_lot_with_no_fx_rate_is_flagged_and_left_out_of_the_totals(app, session, repo):
    _stock(session, repo, "AAPL", [date(2026, 10, 9)], [110.0])
    _holding(repo, "AAPL")
    _holding(repo, "FUND", currency="CAD", price_source="manual", purchase_fx_rate=0.70)    # no FX stored anywhere
    r = _render(app)
    [table] = _tables(r["holdings"])
    statuses = {row["ticker"]: row["status"] for row in table.data}
    assert statuses == {"AAPL": "ok", "FUND": "no CAD FX rate"}
    text = _flatten_text(r["holdings"])
    assert "couldn't be valued" in text and "$1,100.00" in text
    assert "no rate available" in r["fx_status"]
    assert "Left out of history and stats" in _flatten_text(r["stats"])


# ---------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------

def test_deleting_selected_rows_removes_those_lots_and_their_orphaned_marks(app, mixed_portfolio, repo):
    [table] = _tables(_render(app)["holdings"])
    fund_row = next(i for i, row in enumerate(table.data) if row["ticker"] == "FUND")

    delete = _callback(app, "pf-delete-message.children")
    message, counter = delete(1, [fund_row], table.data, 0)
    assert "Deleted 1" in _flatten_text(message) and counter == 1
    assert repo.list_holdings()["ticker"].tolist() == ["AAPL"]
    assert repo.manual_prices().empty                      # no FUND lot left, so its marks went too


def test_delete_needs_a_selection_and_a_confirmation(app, mixed_portfolio, repo):
    [table] = _tables(_render(app)["holdings"])
    delete = _callback(app, "pf-delete-message.children")
    message, counter = delete(1, [], table.data, 0)
    assert "Select at least one row" in _flatten_text(message) and counter is dash.no_update
    assert delete(None, [0], table.data, 0) == (dash.no_update, dash.no_update)    # dialog not confirmed
    assert len(repo.list_holdings()) == 2


# ---------------------------------------------------------------------------
# Risk / return, correlation, history (enough price history to compute them)
# ---------------------------------------------------------------------------

@pytest.fixture()
def price_history_portfolio(session, repo):
    days = pd.bdate_range("2026-07-01", periods=70)
    dates = [d.date() for d in days]
    rng = np.random.default_rng(11)
    walk = lambda start, vol: start * np.cumprod(1 + rng.normal(0.001, vol, len(days)))
    _stock(session, repo, "AAPL", dates, walk(100, 0.012))
    _stock(session, repo, "MSFT", dates, walk(100, 0.010))
    _stock(session, repo, "FLAT", dates, np.full(len(days), 50.0))          # a price that never moves
    _asset(repo, "S&P500_ETF", dates, walk(500, 0.008))
    _asset(repo, "US13W_Yield", dates, np.full(len(days), 4.0))              # percentage points -> 4%
    for ticker, price in (("AAPL", 100.0), ("MSFT", 100.0), ("FLAT", 50.0)):
        _holding(repo, ticker, purchase_date=date(2026, 7, 1), purchase_price=price)
    session.commit()


def test_stats_panel_has_beta_sharpe_and_a_risk_free_note(app, price_history_portfolio):
    r = _render(app)
    [table] = _tables(r["stats"])
    rows = {row["metric"]: row for row in table.data}
    assert rows["Beta vs SPY"]["value"] != "n/a" and "overlapping daily observations" in rows["Beta vs SPY"]["note"]
    assert rows["Sharpe ratio"]["value"] != "n/a" and "4.00%" in rows["Sharpe ratio"]["note"]
    assert rows["Volatility (annualised)"]["value"].endswith("%")
    assert rows["Time-weighted return (total)"]["value"].startswith(("+", "-"))
    text = _flatten_text(r["stats"])
    assert "time-weighted" in text.lower() and "Manually priced" not in text    # no manual positions here


def test_correlation_heatmap_drops_the_flat_series_and_has_no_nans(app, price_history_portfolio):
    """Regression: a never-moving price has undefined correlation; it must be dropped, not shown as NaN."""
    [graph] = _graphs(_render(app)["corr"])
    heat = graph.figure.data[0]
    assert list(heat.x) == ["AAPL", "MSFT"] and list(heat.y) == ["AAPL", "MSFT"]
    assert not np.isnan(np.array(heat.z, dtype=float)).any()
    assert heat.zmin == -1 and heat.zmax == 1


def test_history_chart_shows_value_and_cost_basis(app, price_history_portfolio):
    [graph] = _graphs(_render(app)["history"])
    names = {t.name for t in graph.figure.data}
    assert names == {"Market value", "Cost basis"}
    cost = next(t for t in graph.figure.data if t.name == "Cost basis")
    assert cost.y[-1] == pytest.approx(10 * 100 + 10 * 100 + 10 * 50)


def test_manual_positions_add_the_understated_risk_caveat(app, price_history_portfolio, repo, session):
    _holding(repo, "FUND", price_source="manual", purchase_date=date(2026, 7, 1))
    session.commit()
    r = _render(app)
    assert "understated" in _flatten_text(r["stats"])
    [graph] = _graphs(r["history"])
    assert any("flat between the prices you entered" in (a.text or "") for a in graph.figure.layout.annotations)


def test_charts_follow_the_ft_house_style(app, price_history_portfolio):
    r = _render(app)
    figures = [g.figure for key in ("alloc_class", "alloc_sector", "corr", "history") for g in _graphs(r[key])]
    assert len(figures) == 4
    for fig in figures:
        assert fig.layout.paper_bgcolor == page.FT_PAPER
        assert fig.layout.font.size >= 14                    # a size up from Plotly's default 12
        assert fig.layout.title.x == 0                       # left-aligned title
    history = figures[-1]
    assert history.layout.xaxis.showgrid is False            # horizontal gridlines only
    assert history.layout.yaxis.showgrid is True


def test_too_little_history_says_so_instead_of_inventing_stats(app, session, repo):
    _stock(session, repo, "AAPL", [date(2026, 10, 8), date(2026, 10, 9)], [101.0, 102.0])
    _holding(repo, "AAPL", purchase_date=date(2026, 10, 7))
    session.commit()
    [table] = _tables(_render(app)["stats"])
    rows = {row["metric"]: row for row in table.data}
    assert rows["Volatility (annualised)"]["value"] == "n/a" and "20+ daily observations" in rows["Volatility (annualised)"]["note"]
    assert rows["Beta vs SPY"]["value"] == "n/a"
    assert rows["Time-weighted return (annualised)"]["value"] == "n/a"


# ---------------------------------------------------------------------------
# Dividends received (entered by hand)
# ---------------------------------------------------------------------------

def _add_dividend(app, ticker, amount, pay_date, fx=None):
    return _callback(app, "pf-div-message.children")(1, ticker, amount, pay_date, fx, 0)


def _stock_with_history(session, repo, ticker="AAPL", n=45):
    days = pd.bdate_range("2026-08-03", periods=n)
    _stock(session, repo, ticker, [d.date() for d in days], list(np.linspace(100.0, 110.0, n)))
    return days


def test_dividend_form_offers_held_positions_only(app, session, repo):
    _stock_with_history(session, repo)
    _holding(repo, "AAPL", purchase_date=date(2026, 8, 3))
    r = _render(app)
    assert r["div_options"] == [{"label": "AAPL (USD)", "value": "AAPL"}]
    assert "No dividends recorded" in _flatten_text(r["dividends"])


def test_dividend_flows_into_totals_and_the_ledger(app, session, repo):
    _stock_with_history(session, repo)                       # AAPL closes 100 -> 110
    _holding(repo, "AAPL", shares=10.0, purchase_price=100.0, purchase_date=date(2026, 8, 3))
    message, counter = _add_dividend(app, "AAPL", 25.0, "2026-09-15")
    assert "Added 25.00 USD dividend" in _flatten_text(message) and counter == 1

    r = _render(app)
    text = _flatten_text(r["holdings"])
    assert "Income received $25.00" in text
    assert "Total value $1,125.00" in text                    # value 1,100 + income 25
    assert "Total return +$125.00 (+12.5%)" in text           # (1,100 - 1,000 + 25) / 1,000
    assert "Unrealized P&L +$100.00" in text                  # price P&L alone is unchanged
    ledger = _tables(r["dividends"])[0].data
    assert ledger[0]["ticker"] == "AAPL" and ledger[0]["amount_usd"] == "$25.00"


def test_dividend_makes_total_return_exceed_price_return_and_adds_a_history_line(app, session, repo):
    _stock_with_history(session, repo)
    _holding(repo, "AAPL", purchase_date=date(2026, 8, 3))
    _add_dividend(app, "AAPL", 50.0, "2026-09-15")
    r = _render(app)
    stats = {row["metric"]: row["value"] for row in _tables(r["stats"])[0].data}
    total_key = "Time-weighted return (total), incl. dividends"
    assert total_key in stats and "Time-weighted return (price only)" in stats
    assert float(stats[total_key].strip("%+")) > float(stats["Time-weighted return (price only)"].strip("%+"))
    names = [t.name for g in _graphs(r["history"]) for t in g.figure.data]
    assert "Value incl. dividends" in names


def test_without_dividends_the_stats_and_chart_are_unchanged(app, session, repo):
    _stock_with_history(session, repo)
    _holding(repo, "AAPL", purchase_date=date(2026, 8, 3))
    r = _render(app)
    metrics = [row["metric"] for row in _tables(r["stats"])[0].data]
    assert "Time-weighted return (total)" in metrics and not any("price only" in m for m in metrics)
    assert "Value incl. dividends" not in [t.name for g in _graphs(r["history"]) for t in g.figure.data]
    assert "Income received $0.00" in _flatten_text(r["holdings"])


@pytest.mark.parametrize("kwargs,fragment", [
    (dict(ticker=None, amount=10, pay_date="2026-09-15"), "Choose a position"),
    (dict(ticker="NOPE", amount=10, pay_date="2026-09-15"), "Choose a position"),
    (dict(ticker="AAPL", amount=-5, pay_date="2026-09-15"), "positive number"),
    (dict(ticker="AAPL", amount=10, pay_date="2026-12-01"), "future"),
    (dict(ticker="AAPL", amount=10, pay_date="2026-08-03"), "after you bought"),
])
def test_bad_dividend_entries_are_rejected_and_nothing_is_saved(app, session, repo, kwargs, fragment):
    _holding(repo, "AAPL", purchase_date=date(2026, 8, 3))
    message, counter = _add_dividend(app, kwargs["ticker"], kwargs["amount"], kwargs["pay_date"])
    assert fragment in _flatten_text(message)
    assert repo.list_dividends().empty


def test_a_cad_dividend_is_converted_at_the_pay_date_rate(app, session, repo):
    _holding(repo, "FUND", currency="CAD", price_source="manual", purchase_price=100.0, purchase_fx_rate=0.70,
             purchase_date=date(2026, 8, 3))
    _asset(repo, "CADUSD_fx", [date(2026, 9, 14), date(2026, 9, 16)], [0.72, 0.74])
    _add_dividend(app, "FUND", 40.0, "2026-09-15")             # no typed rate: latest stored on/before = 0.72
    row = repo.list_dividends().iloc[0]
    assert row["currency"] == "CAD" and row["fx_rate"] == pytest.approx(0.72)
    assert "Income received $28.80" in _flatten_text(_render(app)["holdings"])


def test_a_cad_dividend_with_no_rate_anywhere_is_rejected(app, repo):
    _holding(repo, "FUND", currency="CAD", price_source="manual", purchase_fx_rate=0.70, purchase_date=date(2026, 8, 3))
    message, _ = _add_dividend(app, "FUND", 40.0, "2026-09-15")
    assert "No CAD->USD rate" in _flatten_text(message) and repo.list_dividends().empty


def test_deleting_selected_dividends(app, session, repo):
    _holding(repo, "AAPL", purchase_date=date(2026, 8, 3))
    _add_dividend(app, "AAPL", 10.0, "2026-09-15")
    _add_dividend(app, "AAPL", 12.0, "2026-10-01")
    data = _tables(_render(app)["dividends"])[0].data
    delete = _callback(app, "pf-div-delete-message.children")
    assert "Select at least one" in _flatten_text(delete(1, [], data, 0)[0])
    message, counter = delete(1, [0], data, 0)
    assert "Deleted 1 dividend" in _flatten_text(message) and counter == 1
    assert repo.list_dividends()["amount"].tolist() == [12.0]


def test_deleting_the_last_lot_of_a_ticker_drops_its_dividends(app, repo):
    lot_id = _holding(repo, "AAPL", purchase_date=date(2026, 8, 3))
    _add_dividend(app, "AAPL", 10.0, "2026-09-15")
    repo.delete_holdings([lot_id])
    assert repo.list_dividends().empty
