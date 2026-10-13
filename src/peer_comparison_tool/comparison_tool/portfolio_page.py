"""
Portfolio page: holdings, allocation, risk/return, correlation and value
history, all reported in USD.

Unlike the other pages this one is *not* fed a DataFrame loaded once at
startup (`DashboardData`): holdings, hand-entered prices and FX overrides are
written from the page itself, so every render re-reads the database through a
session. (This is the one deliberate exception to "load once at startup".)

Layout, top to bottom:
  1. Add position (ticker, shares, purchase price/date, currency, price source)
  2. Update manual prices / FX -- for positions the pipeline can't price (e.g.
     CAD-hedged funds), and an FX override for the CAD->USD rate
  3. Holdings table (select rows to delete)
  4. Dividends received (entered by hand; select rows to delete)
  5. Allocation: asset class and sector pies
  6. Risk / return stats
  7. Correlation heatmap
  8. Portfolio value history

Each lot has a currency and a price source. "Auto" lots are priced from the
stored market data; "manual" lots from prices typed in here, held flat
between entries. Everything non-USD is converted at the current CAD->USD
rate (the pipeline's `CADUSD_fx` series unless a manual rate is at least as
recent); USD cost basis uses the rate on the purchase date. Dividends are cash
the user types in as received; they count towards total value and total
return (see the transforms docstring). The maths lives in
`data/transforms/portfolio.py`.

Charts follow the same Financial Times house style as the Market Conditions
page (pale paper background, left-aligned title, horizontal gridlines only,
text a size up from Plotly's default); tables stay in the app's dark theme.
"""
from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from typing import Callable

import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dash_table, dcc, html
from dash.dependencies import Input, Output, State

from src.peer_comparison_tool.data.database import init_db, session_scope
from src.peer_comparison_tool.data.portfolio_repository import PortfolioRepository
from src.peer_comparison_tool.data.transforms import portfolio as pf

from .styles import colors

logger = logging.getLogger(__name__)

UP_COLOR = "#55efc4"
DOWN_COLOR = "#d63031"

# Financial Times house style for the charts (same values as
# market_conditions_page.py).
FT_PAPER = "#FFF1E5"
FT_TEXT = "#33302E"
FT_MUTED = "#66605C"
FT_GRID = "#E6D9CE"
FT_BLUE = "#0F5499"
FT_CLARET = "#990F3D"
FT_TEAL = "#0D7680"
FT_OXFORD = "#262A33"
FT_MANDARIN = "#FF8833"
FT_PALETTE = [FT_BLUE, FT_CLARET, FT_TEAL, FT_MANDARIN, FT_OXFORD, "#96CC28", "#A7A59B", "#593380"]
FT_FONT = "Metric, 'Helvetica Neue', Helvetica, Arial, sans-serif"
FT_BASE_FONT_SIZE = 14  # Plotly's default is 12
FT_SOURCE = "Source: Yahoo Finance via yfinance; manual prices and FX rates entered by the user"

HOLDING_TABLE_COLUMNS = [
    ("ticker", "Ticker"), ("name", "Name"), ("asset_class", "Class"), ("currency", "Ccy"),
    ("shares", "Shares"), ("price", "Price"), ("price_date", "Price date"), ("source", "Priced"),
    ("fx", "FX (USD)"), ("value", "Value (USD)"), ("cost", "Cost (USD)"), ("pnl", "P&L (USD)"),
    ("pnl_pct", "P&L %"), ("weight", "Weight"), ("status", "Status"),
]

ASSET_CLASS_OPTIONS = [{"label": c.title(), "value": c} for c in pf.ASSET_CLASS_CHOICES]
CURRENCY_OPTIONS = [{"label": c, "value": c} for c in pf.SUPPORTED_CURRENCIES]
SOURCE_OPTIONS = [
    {"label": "Auto (stored market data)", "value": "auto"},
    {"label": "Manual (I'll enter prices)", "value": "manual"},
]
DIVIDEND_TABLE_COLUMNS = [
    ("ticker", "Ticker"), ("pay_date", "Pay date"), ("amount", "Amount (local)"), ("currency", "Ccy"),
    ("fx", "FX (USD)"), ("amount_usd", "Amount (USD)"),
]
FX_CURRENCY_OPTIONS = [{"label": f"{c} -> USD", "value": c} for c in pf.FX_SERIES_BY_CURRENCY]

SessionScopeFn = Callable[[], AbstractContextManager]


def _today() -> date:
    """Indirection so tests can pin the date."""
    return date.today()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def _card(title: str, body, margin: bool = True) -> dbc.Row:
    return dbc.Row(
        dbc.Col(
            dbc.Card([
                dbc.CardHeader(title, style={"color": colors["text"], "backgroundColor": colors["background"]}),
                dbc.CardBody(body, style={"backgroundColor": colors["background"]}),
            ], style={"backgroundColor": colors["background"], **({"marginBottom": "20px"} if margin else {})}),
            width=12,
        )
    )


def _field(label: str, control, width: int) -> dbc.Col:
    return dbc.Col([html.Label(label, style={"color": colors["text"], "fontSize": "0.85rem"}), control], width=width,
                   className="mb-2")


def _date_picker(component_id: str) -> dcc.DatePickerSingle:
    return dcc.DatePickerSingle(id=component_id, date=_today().isoformat(), display_format="YYYY-MM-DD",
                                max_date_allowed=_today().isoformat())


def _add_position_form() -> html.Div:
    return html.Div([
        dbc.Row([
            _field("Ticker", dbc.Input(id="pf-ticker", type="text", placeholder="e.g. AAPL"), 2),
            _field("Name (optional)", dbc.Input(id="pf-name", type="text"), 3),
            _field("Asset class", dbc.Select(id="pf-asset-class", options=ASSET_CLASS_OPTIONS, value="stock"), 2),
            _field("Sector (optional)", dbc.Input(id="pf-sector", type="text"), 3),
            _field("Priced", dbc.Select(id="pf-source", options=SOURCE_OPTIONS, value="auto"), 2),
        ]),
        dbc.Row([
            _field("Currency", dbc.Select(id="pf-currency", options=CURRENCY_OPTIONS, value="USD"), 2),
            _field("Shares", dbc.Input(id="pf-shares", type="number", min=0), 2),
            _field("Purchase price (per share, in its currency)",
                   dbc.Input(id="pf-purchase-price", type="number", min=0), 3),
            _field("Purchase date", _date_picker("pf-purchase-date"), 2),
            _field("USD per 1 unit of currency on that date (non-USD only; blank = use stored rate)",
                   dbc.Input(id="pf-purchase-fx", type="number", min=0), 3),
        ]),
        dbc.Button("Add position", id="pf-add-button", color="primary", className="me-3"),
        html.Span(id="pf-add-message", style={"color": colors["text"]}),
    ])


def _manual_update_form() -> html.Div:
    return html.Div([
        html.H6("Manual price (positions priced manually)", style={"color": colors["text"]}),
        dbc.Row([
            _field("Position", dbc.Select(id="pf-price-ticker", options=[]), 3),
            _field("Price per share (in the position's currency)", dbc.Input(id="pf-price-value", type="number", min=0), 3),
            _field("As of", _date_picker("pf-price-date"), 2),
            dbc.Col(dbc.Button("Save price", id="pf-price-button", color="secondary"), width=2, className="mt-4"),
        ]),
        html.Span(id="pf-price-message", style={"color": colors["text"]}),
        html.Hr(style={"borderColor": colors["text"], "opacity": 0.3}),
        html.H6("FX rate override", style={"color": colors["text"]}),
        html.Div(id="pf-fx-status", style={"color": colors["text"], "fontSize": "0.9rem", "marginBottom": "8px"}),
        dbc.Row([
            _field("Currency", dbc.Select(id="pf-fx-currency", options=FX_CURRENCY_OPTIONS,
                                          value=next(iter(pf.FX_SERIES_BY_CURRENCY), None)), 2),
            _field("USD per 1 unit", dbc.Input(id="pf-fx-rate", type="number", min=0), 3),
            _field("As of", _date_picker("pf-fx-date"), 2),
            dbc.Col(dbc.Button("Save FX rate", id="pf-fx-button", color="secondary"), width=2, className="mt-4"),
        ]),
        html.Span(id="pf-fx-message", style={"color": colors["text"]}),
    ])


def _dividend_form() -> html.Div:
    return html.Div([
        dbc.Row([
            _field("Position", dbc.Select(id="pf-div-ticker", options=[]), 3),
            _field("Total cash received (in the position's currency)",
                   dbc.Input(id="pf-div-amount", type="number", min=0), 3),
            _field("Pay date", _date_picker("pf-div-date"), 2),
            _field("USD per 1 unit on that date (non-USD only; blank = use stored rate)",
                   dbc.Input(id="pf-div-fx", type="number", min=0), 4),
        ]),
        dbc.Button("Add dividend", id="pf-div-button", color="primary", className="me-3"),
        html.Span(id="pf-div-message", style={"color": colors["text"]}),
        html.Div(id="pf-dividends-content", style={"marginTop": "16px"}),
        html.Div(id="pf-div-delete-message", style={"color": colors["text"], "marginTop": "8px"}),
    ])


def get_portfolio_page_layout() -> html.Div:
    return dbc.Container([
        # Bumped by the add / delete / price / FX / dividend callbacks; the render callback reads all six.
        dcc.Store(id="pf-refresh-add", data=0),
        dcc.Store(id="pf-refresh-delete", data=0),
        dcc.Store(id="pf-refresh-price", data=0),
        dcc.Store(id="pf-refresh-fx", data=0),
        dcc.Store(id="pf-refresh-income", data=0),
        dcc.Store(id="pf-refresh-incomedel", data=0),

        dbc.Row([
            dbc.Col(html.H1("Portfolio", style={"color": colors["text"], "textAlign": "center"}),
                    width=10, className="mb-4"),
            dbc.Col(dbc.Button("Return to Home", id="back-to-home", color="primary", className="mb-3"), width=2),
        ], align="center"),

        dbc.Row(dbc.Col(dbc.Alert(
            "All values are in USD. Positions priced manually (e.g. CAD-hedged funds the pipeline can't see) "
            "use the last price you entered, so update them when you want a current value. Non-USD positions are "
            "converted at the current FX rate shown below; USD cost basis uses the rate on the purchase date.",
            color="warning", style={"marginBottom": "20px"}), width=12)),

        _card("Add position", _add_position_form()),
        _card("Update manual prices and FX", _manual_update_form()),
        # The delete message sits outside the re-rendered content so it survives the refresh the delete triggers.
        _card("Holdings", [html.Div(id="pf-holdings-content"),
                           html.Div(id="pf-delete-message", style={"color": colors["text"], "marginTop": "8px"})]),
        _card("Dividends received", _dividend_form()),
        dbc.Row([
            dbc.Col(_card("Allocation: asset class", html.Div(id="pf-alloc-class")), width=6),
            dbc.Col(_card("Allocation: sector", html.Div(id="pf-alloc-sector")), width=6),
        ]),
        _card("Risk and return", html.Div(id="pf-stats-content")),
        _card("Correlation of daily returns", html.Div(id="pf-corr-content")),
        _card("Portfolio value history", html.Div(id="pf-history-content"), margin=False),
    ], fluid=True, style={"backgroundColor": colors["background"]})


# ---------------------------------------------------------------------------
# State: everything one render needs, read in one session
# ---------------------------------------------------------------------------

@dataclass
class PortfolioState:
    holdings: pd.DataFrame
    positions: pd.DataFrame
    totals: dict
    fx_current: dict[str, pf.FxRate | None]
    analytics: pf.PortfolioAnalytics
    risk_free_rate: float | None
    manual_tickers: dict[str, str]  # manually priced ticker -> currency
    dividends: pd.DataFrame  # ledger with amount_usd
    held: dict[str, tuple[str, date]]  # ticker -> (currency, first purchase date)


def _load_state(scope: SessionScopeFn, today: date) -> PortfolioState:
    with scope() as session:
        repo = PortfolioRepository(session)
        holdings = repo.list_holdings()
        manual_prices = repo.manual_prices()
        manual_fx = repo.manual_fx_rates()
        risk_free = repo.latest_risk_free_rate()
        dividends = repo.list_dividends()
        non_base = sorted(set(holdings["currency"]) - {pf.BASE_CURRENCY}) if not holdings.empty else []
        pipeline_fx = {ccy: repo.fx_history(ccy) for ccy in non_base}
        auto_tickers = holdings.loc[holdings["price_source"] == "auto", "ticker"].unique().tolist() \
            if not holdings.empty else []
        auto_prices = repo.price_history(auto_tickers)
        benchmark = repo.price_history([pf.BENCHMARK_TICKER])

    prices = pf.latest_position_prices(holdings, auto_prices, manual_prices) if not holdings.empty \
        else pd.DataFrame(columns=["id", "price_local", "price_date", "price_basis"])
    fx_current = {ccy: pf.resolve_current_fx(ccy, pipeline_fx.get(ccy), manual_fx) for ccy in non_base}
    positions = pf.value_positions(holdings, prices, fx_current, today)
    analytics = pf.analyze_portfolio(holdings, auto_prices, manual_prices, pipeline_fx, manual_fx, benchmark,
                                     risk_free, dividends)
    manual = holdings[holdings["price_source"] == "manual"] if not holdings.empty else holdings
    manual_tickers = dict(zip(manual["ticker"], manual["currency"])) if not holdings.empty else {}
    held = {}
    if not holdings.empty:
        for ticker, group in holdings.groupby("ticker"):
            held[str(ticker)] = (str(group["currency"].iloc[0]), min(group["purchase_date"]))
    return PortfolioState(holdings, positions, pf.portfolio_totals(positions, dividends), fx_current, analytics,
                          risk_free, manual_tickers, pf.dividends_with_usd(dividends), held)


# ---------------------------------------------------------------------------
# Formatting and building blocks
# ---------------------------------------------------------------------------

def _usd(value, decimals: int = 2) -> str:
    return "n/a" if value is None or pd.isna(value) else f"${value:,.{decimals}f}"


def _signed_usd(value) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{'+' if value >= 0 else '-'}${abs(value):,.2f}"


def _pct(value, signed: bool = False, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:+.{decimals}f}%" if signed else f"{value * 100:.{decimals}f}%"


def _num(value, decimals: int = 2, fallback: str = "n/a") -> str:
    return fallback if value is None or pd.isna(value) else f"{value:,.{decimals}f}"


def _fmt_date(value) -> str:
    return "n/a" if value is None or pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def _message(text: str, ok: bool = False) -> html.Span:
    return html.Span(text, style={"color": UP_COLOR if ok else DOWN_COLOR})


def _text(text: str, **style) -> html.P:
    return html.P(text, style={"color": colors["text"], **style})


def _note(text: str) -> html.P:
    return html.P(text, style={"color": colors["text"], "fontSize": "0.85rem", "opacity": 0.85, "marginTop": "10px"})


def _dark_table(columns: list[dict], rows: list[dict], style_data_conditional=None, **kwargs) -> dash_table.DataTable:
    return dash_table.DataTable(
        columns=columns, data=rows,
        style_header={"backgroundColor": colors["background"], "color": colors["text"], "fontWeight": "bold"},
        style_data={"backgroundColor": colors["background"], "color": colors["text"]},
        style_cell={"minWidth": "80px", "textAlign": "left"},
        style_data_conditional=style_data_conditional or [], **kwargs,
    )


def _sign_style(raw_column: str, value_column: str) -> list[dict]:
    """Color `value_column` by the sign of the numeric `raw_column` (the
    displayed text is already formatted, so the sign is read from a parallel
    raw field)."""
    return [
        {"if": {"filter_query": f"{{{raw_column}}} > 0", "column_id": value_column}, "color": UP_COLOR},
        {"if": {"filter_query": f"{{{raw_column}}} < 0", "column_id": value_column}, "color": DOWN_COLOR},
    ]


def _ft_figure(title: str, subtitle: str, y_suffix: str = "", y_prefix: str = "") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=f"{title}<br><sup>{subtitle}</sup>", x=0, xanchor="left",
                   font=dict(size=FT_BASE_FONT_SIZE + 6, color=FT_TEXT)),
        paper_bgcolor=FT_PAPER, plot_bgcolor=FT_PAPER,
        font=dict(family=FT_FONT, size=FT_BASE_FONT_SIZE, color=FT_TEXT),
        xaxis=dict(showgrid=False, linecolor=FT_TEXT, ticks="outside", tickcolor=FT_TEXT),
        yaxis=dict(showgrid=True, gridcolor=FT_GRID, zeroline=False, ticksuffix=y_suffix, tickprefix=y_prefix,
                   side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
        margin=dict(l=20, r=20, t=100, b=70),
        annotations=[dict(text=FT_SOURCE, xref="paper", yref="paper", x=0, y=-0.16, xanchor="left",
                          showarrow=False, font=dict(size=FT_BASE_FONT_SIZE - 2, color=FT_MUTED))],
    )
    return fig


def _graph(fig: go.Figure) -> dcc.Graph:
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"marginTop": "10px"})


# ---------------------------------------------------------------------------
# Section renderers (pure functions of the state)
# ---------------------------------------------------------------------------

def _fx_status_text(state: PortfolioState) -> str:
    """One line per supported non-USD currency saying which rate is in use."""
    parts = []
    for currency in pf.FX_SERIES_BY_CURRENCY:
        fx = state.fx_current.get(currency)
        if fx is None:
            parts.append(f"{currency}->USD: no rate available. Enter one below, or run the pipeline to fetch "
                         f"{pf.FX_SERIES_BY_CURRENCY[currency]}.")
        else:
            parts.append(f"{currency}->USD: {fx.rate:.4f} ({fx.source}, as of {_fmt_date(fx.as_of)})")
    return "  |  ".join(parts)


def _render_holdings(state: PortfolioState):
    positions = state.positions
    if positions.empty:
        return _text("No positions yet. Add one above.")

    totals = state.totals
    pnl_color = UP_COLOR if totals["unrealized_pnl_usd"] >= 0 else DOWN_COLOR
    summary = html.Div([
        html.Span(f"Value {_usd(totals['total_value_usd'])}", style={"marginRight": "24px", "fontWeight": "bold"}),
        html.Span(f"Income received {_usd(totals['income_usd'])}", style={"marginRight": "24px"}),
        html.Span(f"Total value {_usd(totals['total_value_with_income_usd'])}",
                  style={"marginRight": "24px", "fontWeight": "bold"}),
        html.Span(f"Cost {_usd(totals['total_cost_usd'])}", style={"marginRight": "24px"}),
        html.Span(f"Unrealized P&L {_signed_usd(totals['unrealized_pnl_usd'])} "
                  f"({_pct(totals['unrealized_pnl_pct'], signed=True)})",
                  style={"color": pnl_color, "marginRight": "24px"}),
        html.Span(f"Total return {_signed_usd(totals['total_return_usd'])} "
                  f"({_pct(totals['total_return_pct'], signed=True)})",
                  style={"color": UP_COLOR if totals["total_return_usd"] >= 0 else DOWN_COLOR, "fontWeight": "bold"}),
    ], style={"color": colors["text"], "marginBottom": "12px"})

    rows = []
    for p in positions.itertuples(index=False):
        rows.append({
            "id": int(p.id),
            "ticker": p.ticker,
            "name": "" if pd.isna(p.name) else p.name,
            "asset_class": p.asset_class,
            "currency": p.currency,
            "shares": _num(p.shares, 4).rstrip("0").rstrip("."),
            "price": _num(p.price_local, 2),
            "price_date": _fmt_date(p.price_date),
            "source": p.price_source,
            "fx": "1" if p.currency == pf.BASE_CURRENCY else _num(p.fx_rate, 4),
            "value": _usd(p.market_value_usd),
            "cost": _usd(p.cost_basis_usd),
            "pnl": _signed_usd(p.unrealized_pnl_usd),
            "pnl_pct": _pct(p.unrealized_pnl_pct, signed=True),
            "weight": _pct(p.weight),
            "status": p.status,
            "_pnl_raw": 0 if pd.isna(p.unrealized_pnl_usd) else float(p.unrealized_pnl_usd),
        })

    # Sorting/filtering stays off: row selection indexes `data` directly, and a
    # sorted view would make "selected row 0" ambiguous.
    table = _dark_table(
        [{"name": label, "id": col} for col, label in HOLDING_TABLE_COLUMNS], rows,
        style_data_conditional=_sign_style("_pnl_raw", "pnl") + _sign_style("_pnl_raw", "pnl_pct") + [
            {"if": {"filter_query": '{status} != "ok"', "column_id": "status"}, "color": "#fdcb6e"}],
        id="pf-holdings-table", row_selectable="multi", selected_rows=[], page_size=50,
    )

    notes = []
    stale = positions[(positions["price_source"] == "manual") & (positions["price_age_days"] > pf.STALE_MANUAL_DAYS)]
    if not stale.empty:
        names = ", ".join(sorted(set(stale["ticker"])))
        notes.append(f"Manual prices older than {pf.STALE_MANUAL_DAYS} days: {names}. Update them for a current value.")
    if totals["n_unvalued"]:
        notes.append(f"{totals['n_unvalued']} position(s) couldn't be valued (see Status) and are left out of the "
                     "totals, allocation and P&L above.")

    delete_button = dcc.ConfirmDialogProvider(
        children=dbc.Button("Delete selected", color="danger", size="sm", className="mt-2"),
        id="pf-delete-provider", message="Delete the selected positions? This can't be undone.")
    return [summary, table, delete_button, *[_note(n) for n in notes]]


def _render_dividends(state: PortfolioState):
    div = state.dividends
    if div.empty:
        return _text("No dividends recorded yet. Add one above when you receive it.")
    rows = [{
        "id": int(d.id), "ticker": d.ticker, "pay_date": _fmt_date(d.pay_date), "amount": _num(d.amount, 2),
        "currency": d.currency, "fx": "1" if d.currency == pf.BASE_CURRENCY else _num(d.fx_rate, 4),
        "amount_usd": _usd(d.amount_usd),
    } for d in div.itertuples(index=False)]
    table = _dark_table([{"name": label, "id": col} for col, label in DIVIDEND_TABLE_COLUMNS], rows,
                        id="pf-dividends-table", row_selectable="multi", selected_rows=[], page_size=50)
    delete_button = dcc.ConfirmDialogProvider(
        children=dbc.Button("Delete selected", color="danger", size="sm", className="mt-2"),
        id="pf-div-delete-provider", message="Delete the selected dividends? This can't be undone.")
    return [table, delete_button,
            _note("Dividends are cash received, not reinvested. They add to total value and total return.")]


def _render_pie(positions: pd.DataFrame, by: str, title: str):
    alloc = pf.allocation(positions, by)
    if alloc.empty:
        return _text("Nothing to show: no positions have a value yet.")
    fig = _ft_figure(title, "Share of portfolio value (USD)")
    fig.update_layout(hovermode="closest", legend=dict(orientation="h", x=0, y=-0.05), margin=dict(l=20, r=20, t=100, b=90),
                      yaxis=dict(visible=False), xaxis=dict(visible=False))
    fig.add_trace(go.Pie(
        labels=alloc["label"], values=alloc["market_value_usd"], hole=0.45, sort=False,
        marker=dict(colors=[FT_PALETTE[i % len(FT_PALETTE)] for i in range(len(alloc))],
                    line=dict(color=FT_PAPER, width=2)),
        textinfo="percent", textfont=dict(size=FT_BASE_FONT_SIZE + 1), direction="clockwise",
        hovertemplate="%{label}: $%{value:,.0f} (%{percent})<extra></extra>"))
    return _graph(fig)


def _render_stats(state: PortfolioState):
    stats = state.analytics.stats
    if state.positions.empty:
        return _text("Add a position to see risk and return.")
    if not stats or stats.get("n_obs", 0) == 0:
        return _text("Not enough price history yet: returns start the day after a position's purchase date.")

    rf = stats["risk_free_rate"]
    need = f"needs {pf.MIN_OBS_STATS}+ daily observations"
    has_income = state.analytics.has_income
    rows = [
        ("Time-weighted return (total)" + (", incl. dividends" if has_income else ""),
         _pct(stats["twr_total"], signed=True),
         f"{stats['n_obs']} daily observations, {_fmt_date(stats['start'])} to {_fmt_date(stats['end'])}"),
        ("Time-weighted return (annualised)" + (", incl. dividends" if has_income else ""),
         _pct(stats["twr_annualized"], signed=True),
         "" if stats["twr_annualized"] is not None else f"needs {pf.MIN_OBS_ANNUALIZE}+ daily observations"),
        *([("Time-weighted return (price only)", _pct(stats.get("twr_price_total"), signed=True),
            "excludes dividends received; the gap to the line above is the income")] if has_income else []),
        ("Volatility (annualised)", _pct(stats["volatility"]),
         "" if stats["volatility"] is not None else need),
        ("Sharpe ratio", _num(stats["sharpe"]),
         (f"risk-free rate {rf * 100:.2f}% (13-week T-bill)" if rf is not None else "no risk-free rate stored")
         if stats["sharpe"] is not None or rf is None else need),
        (f"Beta vs {pf.BENCHMARK_TICKER}", _num(stats["beta"]),
         f"{stats['beta_n_obs']} overlapping daily observations" if stats["beta"] is not None
         else (f"no overlapping {pf.BENCHMARK_TICKER} history stored" if stats["beta_n_obs"] == 0
               else f"{need}; {stats['beta_n_obs']} overlapping so far")),
        ("Max drawdown", _pct(stats["max_drawdown"]), "peak-to-trough, from the start of the series"),
    ]
    data = [{"metric": m, "value": v, "note": n} for m, v, n in rows]
    children = [_dark_table([{"name": "Metric", "id": "metric"}, {"name": "Value", "id": "value"},
                             {"name": "Note", "id": "note"}], data, style_cell_conditional=[
                                 {"if": {"column_id": "note"}, "minWidth": "320px"}])]

    notes = ["Returns are time-weighted in USD (so they include currency moves), computed from the positions held "
             "at each prior close: buying more shares doesn't count as performance."]
    if has_income:
        notes.append("Dividends you entered count as return on their pay date (they are not new money), so "
                     "volatility, Sharpe, beta and drawdown here are on total return.")
    if state.analytics.includes_manual:
        notes.append("Manually priced positions only change when you enter a price, so they dampen volatility and "
                     "beta and show no day-to-day correlation. Treat these figures as understated while any are held.")
    if state.analytics.excluded_labels:
        notes.append("Left out of history and stats (no FX rate or price path): "
                     + ", ".join(sorted(set(state.analytics.excluded_labels))) + ".")
    children += [_note(n) for n in notes]
    return children


def _render_correlation(state: PortfolioState):
    corr = state.analytics.correlation
    if corr.empty:
        return _text(f"Needs at least two market-priced positions with {pf.MIN_OBS_CORRELATION}+ days of price "
                     "history. Manually priced positions are excluded (they have no daily prices), as is any "
                     "position whose price never changes.")
    labels = list(corr.columns)
    fig = _ft_figure("Correlation of daily USD returns", "Market-priced positions; -1 to +1")
    fig.update_layout(hovermode="closest", yaxis=dict(autorange="reversed", showgrid=False, side="left"),
                      xaxis=dict(showgrid=False, side="bottom"))
    fig.add_trace(go.Heatmap(
        z=corr.values, x=labels, y=labels, zmin=-1, zmax=1,
        colorscale=[[0, FT_CLARET], [0.5, FT_PAPER], [1, FT_BLUE]],
        text=np.round(corr.values, 2), texttemplate="%{text}", textfont=dict(size=FT_BASE_FONT_SIZE),
        colorbar=dict(thickness=12)))
    return _graph(fig)


def _render_history(state: PortfolioState):
    value = state.analytics.value_history
    if value.empty:
        return _text("Add a position to see its value over time.")
    fig = _ft_figure("Portfolio value", "USD, daily", y_prefix="$")
    fig.add_trace(go.Scatter(x=value.index, y=value.values, name="Market value", line=dict(color=FT_BLUE, width=2.5)))
    cost = state.analytics.cost_history
    if not cost.empty:
        fig.add_trace(go.Scatter(x=cost.index, y=cost.values, name="Cost basis",
                                 line=dict(color=FT_CLARET, width=2, dash="dot", shape="hv")))
    total = state.analytics.total_value_history
    if state.analytics.has_income and not total.empty:
        fig.add_trace(go.Scatter(x=total.index, y=total.values, name="Value incl. dividends",
                                 line=dict(color=FT_TEAL, width=2.5)))
    if state.analytics.includes_manual:
        fig.add_annotation(text="Manually priced positions are flat between the prices you entered.",
                           xref="paper", yref="paper", x=0, y=1.02, xanchor="left", showarrow=False,
                           font=dict(size=FT_BASE_FONT_SIZE - 1, color=FT_MUTED))
    return _graph(fig)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def register_portfolio_callback(app: dash.Dash, session_scope_fn: SessionScopeFn | None = None) -> None:
    """Wire the page. `session_scope_fn` defaults to the app's real
    `session_scope`; tests pass one that yields an in-memory session. With
    the real one, the portfolio tables are created if they don't exist yet
    (`init_db` only ever adds missing tables)."""
    if session_scope_fn is None:
        init_db()
        session_scope_fn = session_scope
    scope = session_scope_fn

    refresh_inputs = [Input(f"pf-refresh-{k}", "data") for k in ("add", "delete", "price", "fx", "income", "incomedel")]

    @app.callback(
        [Output("pf-holdings-content", "children"), Output("pf-alloc-class", "children"),
         Output("pf-alloc-sector", "children"), Output("pf-stats-content", "children"),
         Output("pf-corr-content", "children"), Output("pf-history-content", "children"),
         Output("pf-price-ticker", "options"), Output("pf-fx-status", "children"),
         Output("pf-dividends-content", "children"), Output("pf-div-ticker", "options")],
        refresh_inputs,
    )
    def render(*_):
        state = _load_state(scope, _today())
        manual_options = [{"label": f"{t} ({c})", "value": t} for t, c in sorted(state.manual_tickers.items())]
        return (
            _render_holdings(state),
            _render_pie(state.positions, "asset_class", "By asset class"),
            _render_pie(state.positions, "sector", "By sector"),
            _render_stats(state),
            _render_correlation(state),
            _render_history(state),
            manual_options,
            _fx_status_text(state),
            _render_dividends(state),
            [{"label": f"{t} ({c})", "value": t} for t, (c, _) in sorted(state.held.items())],
        )

    @app.callback(
        [Output("pf-add-message", "children"), Output("pf-refresh-add", "data")],
        [Input("pf-add-button", "n_clicks")],
        [State("pf-ticker", "value"), State("pf-name", "value"), State("pf-asset-class", "value"),
         State("pf-sector", "value"), State("pf-source", "value"), State("pf-currency", "value"),
         State("pf-shares", "value"), State("pf-purchase-price", "value"), State("pf-purchase-date", "date"),
         State("pf-purchase-fx", "value"), State("pf-refresh-add", "data")],
        prevent_initial_call=True,
    )
    def add_position(n_clicks, ticker, name, asset_class, sector, source, currency, shares, purchase_price,
                     purchase_date, purchase_fx, counter):
        today = _today()
        clean_ticker = str(ticker).strip().upper() if ticker else ""
        with scope() as session:
            repo = PortfolioRepository(session)
            has_history = None
            profile = None
            if clean_ticker:
                has_history = not repo.price_history([clean_ticker]).empty
                profile = repo.company_profile(clean_ticker)
            record, error = pf.validate_new_holding(
                ticker=ticker, name=name or (profile or {}).get("name"), asset_class=asset_class,
                sector=sector or (profile or {}).get("sector"), currency=currency, price_source=source,
                shares=shares, purchase_price=purchase_price, purchase_date=purchase_date,
                purchase_fx_rate=purchase_fx, today=today, has_price_history=has_history,
                pipeline_fx=repo.fx_history(currency) if currency in pf.FX_SERIES_BY_CURRENCY else None,
                manual_fx=repo.manual_fx_rates(),
            )
            if error:
                return _message(error), dash.no_update
            repo.add_holding(**record)
        return _message(f"Added {record['ticker']}.", ok=True), (counter or 0) + 1

    @app.callback(
        [Output("pf-delete-message", "children"), Output("pf-refresh-delete", "data")],
        [Input("pf-delete-provider", "submit_n_clicks")],
        [State("pf-holdings-table", "selected_rows"), State("pf-holdings-table", "data"),
         State("pf-refresh-delete", "data")],
        prevent_initial_call=True,
    )
    def delete_positions(submit_n_clicks, selected_rows, table_data, counter):
        if not submit_n_clicks:
            return dash.no_update, dash.no_update
        if not selected_rows or not table_data:
            return _message("Select at least one row first."), dash.no_update
        ids = [table_data[i]["id"] for i in selected_rows if 0 <= i < len(table_data)]
        with scope() as session:
            deleted = PortfolioRepository(session).delete_holdings(ids)
        return _message(f"Deleted {deleted} position(s).", ok=True), (counter or 0) + 1

    @app.callback(
        [Output("pf-price-message", "children"), Output("pf-refresh-price", "data")],
        [Input("pf-price-button", "n_clicks")],
        [State("pf-price-ticker", "value"), State("pf-price-value", "value"), State("pf-price-date", "date"),
         State("pf-refresh-price", "data")],
        prevent_initial_call=True,
    )
    def save_manual_price(n_clicks, ticker, price, as_of, counter):
        with scope() as session:
            repo = PortfolioRepository(session)
            holdings = repo.list_holdings()
            manual = holdings[holdings["price_source"] == "manual"] if not holdings.empty else holdings
            record, error = pf.validate_manual_price(
                ticker=ticker, price=price, as_of=as_of, today=_today(),
                manual_tickers=dict(zip(manual["ticker"], manual["currency"])) if not manual.empty else {})
            if error:
                return _message(error), dash.no_update
            repo.upsert_manual_price(**record)
        return _message(f"Saved {record['ticker']} at {record['price']:,.2f} {record['currency']} "
                        f"as of {record['as_of_date']}.", ok=True), (counter or 0) + 1

    @app.callback(
        [Output("pf-fx-message", "children"), Output("pf-refresh-fx", "data")],
        [Input("pf-fx-button", "n_clicks")],
        [State("pf-fx-currency", "value"), State("pf-fx-rate", "value"), State("pf-fx-date", "date"),
         State("pf-refresh-fx", "data")],
        prevent_initial_call=True,
    )
    def save_fx_rate(n_clicks, currency, rate, as_of, counter):
        record, error = pf.validate_manual_fx(currency=currency, rate=rate, as_of=as_of, today=_today())
        if error:
            return _message(error), dash.no_update
        with scope() as session:
            PortfolioRepository(session).upsert_manual_fx_rate(**record)
        return _message(f"Saved {record['currency']}->USD {record['rate']:.4f} as of {record['as_of_date']}.",
                        ok=True), (counter or 0) + 1

    @app.callback(
        [Output("pf-div-message", "children"), Output("pf-refresh-income", "data")],
        [Input("pf-div-button", "n_clicks")],
        [State("pf-div-ticker", "value"), State("pf-div-amount", "value"), State("pf-div-date", "date"),
         State("pf-div-fx", "value"), State("pf-refresh-income", "data")],
        prevent_initial_call=True,
    )
    def add_dividend(n_clicks, ticker, amount, pay_date, fx_rate, counter):
        with scope() as session:
            repo = PortfolioRepository(session)
            holdings = repo.list_holdings()
            held = {}
            if not holdings.empty:
                for t, group in holdings.groupby("ticker"):
                    held[str(t)] = (str(group["currency"].iloc[0]), min(group["purchase_date"]))
            currency = held.get(str(ticker).strip().upper() if ticker else "", (None, None))[0]
            record, error = pf.validate_new_dividend(
                ticker=ticker, pay_date=pay_date, amount=amount, fx_rate=fx_rate, held=held, today=_today(),
                pipeline_fx=repo.fx_history(currency) if currency in pf.FX_SERIES_BY_CURRENCY else None,
                manual_fx=repo.manual_fx_rates())
            if error:
                return _message(error), dash.no_update
            repo.add_dividend(**record)
        return _message(f"Added {record['amount']:,.2f} {record['currency']} dividend from {record['ticker']} "
                        f"({record['pay_date']}).", ok=True), (counter or 0) + 1

    @app.callback(
        [Output("pf-div-delete-message", "children"), Output("pf-refresh-incomedel", "data")],
        [Input("pf-div-delete-provider", "submit_n_clicks")],
        [State("pf-dividends-table", "selected_rows"), State("pf-dividends-table", "data"),
         State("pf-refresh-incomedel", "data")],
        prevent_initial_call=True,
    )
    def delete_dividends(submit_n_clicks, selected_rows, table_data, counter):
        if not submit_n_clicks:
            return dash.no_update, dash.no_update
        if not selected_rows or not table_data:
            return _message("Select at least one row first."), dash.no_update
        ids = [table_data[i]["id"] for i in selected_rows if 0 <= i < len(table_data)]
        with scope() as session:
            deleted = PortfolioRepository(session).delete_dividends(ids)
        return _message(f"Deleted {deleted} dividend(s).", ok=True), (counter or 0) + 1
