"""
Pairs-trading screener page.

On-demand, not pipeline-materialized (per Phillip's call): you pick a
ticker list, hit "Screen Pairs," and every combination among them is tested
for cointegration right then, using price history already loaded into the
dashboard at startup (`ticker_series_data` — no extra DB round trip, no
yfinance calls). This is deliberately exploratory-tool framing ("give me
some idea a trade might exist"), not a production signal generator.

Two-step UI, since screening N tickers is O(N^2) pairs but inspecting one
pair in detail is cheap:

1. Screen: `data.transforms.pairs_trading.screen_pairs()` over every
   combination, rendered as a sortable summary table (strongest
   cointegration candidates first).
2. Inspect: clicking a table row re-runs `analyze_pair()` for just that one
   pair (cheap — a single regression + ADF test) to render the spread chart
   with z-score bands and the backtest equity curve.

The backtest is a simplified historical illustration — no transaction
costs, no slippage, one position at a time — and the page says so directly
rather than only in code comments; this is finance-adjacent content, and it
should read as "here's what this specific historical window did," not as a
recommendation or a promise about the future.
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dash_table, dcc, html
from dash.dependencies import Input, Output, State

from src.peer_comparison_tool.data.transforms.pairs_trading import analyze_pair, screen_pairs

from .styles import colors

SUMMARY_COLUMNS = [
    "ticker_a", "ticker_b", "coint_pvalue", "cointegrated", "correlation",
    "current_zscore", "n_trades", "win_rate", "total_realized_pnl",
]
SUMMARY_COLUMN_LABELS = {
    "ticker_a": "Ticker A", "ticker_b": "Ticker B", "coint_pvalue": "Coint. p-value",
    "cointegrated": "Cointegrated", "correlation": "Price Correlation",
    "current_zscore": "Current Z-Score", "n_trades": "Backtest Trades",
    "win_rate": "Backtest Win Rate", "total_realized_pnl": "Backtest Realized P&L (spread units)",
}
DEFAULT_ENTRY_Z = 2.0
DEFAULT_EXIT_Z = 0.5


def get_pairs_trading_page_layout(company_info: pd.DataFrame) -> html.Div:
    ticker_options = [
        {"label": f"{row.ticker} — {row.name}", "value": row.ticker}
        for row in company_info.sort_values("ticker").itertuples()
    ]

    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Pairs Trading Screener", style={"color": colors["text"], "textAlign": "center"}),
                width=10, className="mb-4"),
            dbc.Col(dbc.Button("Return to Home", id="back-to-home", color="primary", className="mb-3"), width=2),
        ], align="center"),

        dbc.Row(
            dbc.Col(
                dbc.Alert(
                    "Exploratory tool only. Cointegration and the backtest below are computed on historical "
                    "close prices with no transaction costs, slippage, or capital constraints, and a past "
                    "relationship between two prices holding is not a guarantee it continues to. This is not "
                    "investment advice — use it to flag pairs worth a closer look, not as a signal to trade on.",
                    color="warning", style={"marginBottom": "20px"},
                ), width=12,
            )
        ),

        dbc.Row([
            dbc.Col([
                html.Label("Select tickers to screen (pick 2+):", style={"color": colors["text"]}),
                dcc.Dropdown(
                    id="pairs-ticker-dropdown", options=ticker_options, multi=True, searchable=True,
                    placeholder="e.g. VISA, MASTERCARD, ...", style={"marginBottom": "15px"},
                ),
            ], width=6),
            dbc.Col([
                html.Label("Entry |z-score|:", style={"color": colors["text"]}),
                dcc.Input(id="pairs-entry-z", type="number", value=DEFAULT_ENTRY_Z, min=0.5, step=0.1,
                          style={"marginBottom": "15px", "width": "100%"}),
            ], width=2),
            dbc.Col([
                html.Label("Exit |z-score|:", style={"color": colors["text"]}),
                dcc.Input(id="pairs-exit-z", type="number", value=DEFAULT_EXIT_Z, min=0.0, step=0.1,
                          style={"marginBottom": "15px", "width": "100%"}),
            ], width=2),
            dbc.Col([
                html.Label(" ", style={"color": colors["text"], "display": "block"}),
                dbc.Button("Screen Pairs", id="pairs-screen-button", color="primary", style={"width": "100%"}),
            ], width=2),
        ], align="end"),

        dbc.Row(dbc.Col(html.Div(id="pairs-screen-status", style={"color": colors["text"], "margin": "10px 0"}))),

        dbc.Row(
            dbc.Col(
                dbc.Card([
                    dbc.CardHeader("Candidate Pairs (click a row to inspect)",
                                   style={"color": colors["text"], "backgroundColor": colors["background"]}),
                    dbc.CardBody(
                        dash_table.DataTable(
                            id="pairs-summary-table",
                            columns=[{"name": SUMMARY_COLUMN_LABELS[c], "id": c} for c in SUMMARY_COLUMNS],
                            data=[],
                            row_selectable="single",
                            sort_action="native",
                            style_header={"backgroundColor": colors["background"], "color": colors["text"], "fontWeight": "bold"},
                            style_data={"backgroundColor": colors["background"], "color": colors["text"]},
                            style_cell={"minWidth": "110px"},
                        ),
                        style={"backgroundColor": colors["background"]},
                    ),
                ], style={"backgroundColor": colors["background"], "marginBottom": "20px"}),
                width=12,
            )
        ),

        dbc.Row(dbc.Col(html.Div(id="pairs-detail-content"), width=12)),
    ], fluid=True, style={"backgroundColor": colors["background"]})


def register_pairs_trading_callback(app: dash.Dash, ticker_series_data: pd.DataFrame) -> None:
    price_by_ticker = {
        ticker: group[["date", "close_price"]].dropna().reset_index(drop=True)
        for ticker, group in ticker_series_data.groupby("ticker")
    }

    @app.callback(
        [Output("pairs-summary-table", "data"), Output("pairs-screen-status", "children")],
        [Input("pairs-screen-button", "n_clicks")],
        [State("pairs-ticker-dropdown", "value"), State("pairs-entry-z", "value"), State("pairs-exit-z", "value")],
    )
    def run_screen(n_clicks, selected_tickers, entry_z, exit_z):
        if not n_clicks or not selected_tickers or len(selected_tickers) < 2:
            return [], "Pick at least two tickers, then click \"Screen Pairs\"."

        frames = {t: price_by_ticker[t] for t in selected_tickers if t in price_by_ticker}
        missing = set(selected_tickers) - set(frames)
        results = screen_pairs(frames, entry_z=entry_z or DEFAULT_ENTRY_Z, exit_z=exit_z or DEFAULT_EXIT_Z)

        if not results:
            status = "No candidate pairs had enough overlapping price history to test."
            if missing:
                status += f" (No price data at all for: {', '.join(sorted(missing))}.)"
            return [], status

        table_rows = [_format_summary_row(r) for r in results]
        n_cointegrated = sum(1 for r in results if r["cointegrated"])
        status = f"Tested {len(results)} pair(s); {n_cointegrated} cointegrated at the 5% level."
        if missing:
            status += f" No price data for: {', '.join(sorted(missing))}."
        return table_rows, status

    @app.callback(
        Output("pairs-detail-content", "children"),
        [Input("pairs-summary-table", "derived_virtual_data"), Input("pairs-summary-table", "derived_virtual_selected_rows")],
        [State("pairs-entry-z", "value"), State("pairs-exit-z", "value")],
    )
    def show_pair_detail(table_data, selected_rows, entry_z, exit_z):
        if not table_data or not selected_rows:
            return html.Div()

        row = table_data[selected_rows[0]]
        ticker_a, ticker_b = row["ticker_a"], row["ticker_b"]
        if ticker_a not in price_by_ticker or ticker_b not in price_by_ticker:
            return html.Div("Price data unavailable for this pair.", style={"color": colors["text"]})

        result = analyze_pair(
            price_by_ticker[ticker_a], price_by_ticker[ticker_b], ticker_a, ticker_b,
            entry_z=entry_z or DEFAULT_ENTRY_Z, exit_z=exit_z or DEFAULT_EXIT_Z,
        )
        if result is None:
            return html.Div("Not enough overlapping price history for this pair.", style={"color": colors["text"]})

        return _build_detail_layout(result)


def _format_summary_row(result: dict) -> dict:
    return {
        "ticker_a": result["ticker_a"],
        "ticker_b": result["ticker_b"],
        "coint_pvalue": round(result["coint_pvalue"], 4),
        "cointegrated": "Yes" if result["cointegrated"] else "No",
        "correlation": round(result["correlation"], 3),
        "current_zscore": round(result["current_zscore"], 2),
        "n_trades": result["n_trades"],
        "win_rate": "n/a" if result["win_rate"] is None else f"{result['win_rate'] * 100:.0f}%",
        "total_realized_pnl": round(result["total_realized_pnl"], 2),
    }


def _build_detail_layout(result: dict) -> html.Div:
    ticker_a, ticker_b = result["ticker_a"], result["ticker_b"]
    spread_df = result["spread_series"]
    spread_mean = spread_df["spread"].mean()
    spread_std = spread_df["spread"].std()

    spread_fig = go.Figure()
    spread_fig.add_trace(go.Scatter(x=spread_df["date"], y=spread_df["spread"], name="Spread", line=dict(color=colors["chart1"])))
    for n_std, dash_style in [(1, "dot"), (2, "dash")]:
        spread_fig.add_hline(y=spread_mean + n_std * spread_std, line_dash=dash_style, line_color="grey", annotation_text=f"+{n_std}σ")
        spread_fig.add_hline(y=spread_mean - n_std * spread_std, line_dash=dash_style, line_color="grey", annotation_text=f"-{n_std}σ")
    spread_fig.add_hline(y=spread_mean, line_color="white", annotation_text="mean")
    spread_fig.update_layout(
        title=f"Spread: {ticker_a} − {result['hedge_ratio']:.3f} × {ticker_b}",
        template="plotly_dark", paper_bgcolor=colors["background"], plot_bgcolor=colors["background"],
    )

    equity_fig = go.Figure()
    equity_curve = result["equity_curve"]
    equity_fig.add_trace(go.Scatter(x=equity_curve.index, y=equity_curve.values, name="Backtest equity", line=dict(color=colors["chart2"])))
    equity_fig.update_layout(
        title="Backtest equity curve (realized + mark-to-market, spread units)",
        template="plotly_dark", paper_bgcolor=colors["background"], plot_bgcolor=colors["background"],
    )

    summary_items = [
        f"Cointegration p-value: {result['coint_pvalue']:.4f} ({'cointegrated' if result['cointegrated'] else 'not cointegrated'} at 5%)",
        f"Price correlation: {result['correlation']:.3f}",
        f"Hedge ratio (units of {ticker_b} per unit of {ticker_a}): {result['hedge_ratio']:.3f}",
        f"Current z-score: {result['current_zscore']:.2f}",
        f"Backtest trades: {result['n_trades']}"
        + (f", win rate {result['win_rate'] * 100:.0f}%" if result["win_rate"] is not None else ""),
        f"Backtest total realized P&L: {result['total_realized_pnl']:.2f} spread units",
    ]
    if result["open_position_at_end"]:
        summary_items.append(f"Position still open at end of window — unrealized P&L: {result['unrealized_pnl_at_end']:.2f} spread units")

    return dbc.Card([
        dbc.CardHeader(f"{ticker_a} vs {ticker_b}", style={"color": colors["text"], "backgroundColor": colors["background"]}),
        dbc.CardBody([
            html.Ul([html.Li(item, style={"color": colors["text"]}) for item in summary_items]),
            dcc.Graph(figure=spread_fig),
            dcc.Graph(figure=equity_fig),
        ], style={"backgroundColor": colors["background"]}),
    ], style={"backgroundColor": colors["background"]})
