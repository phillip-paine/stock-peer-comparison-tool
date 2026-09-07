"""
Peer valuation dispersion screener page.

On-demand, computed entirely from `snapshot_recent_metrics` -- the same
frame `comparison_page.py` already uses, loaded once at dashboard startup
(see `data_loader.py`). No network calls, no caching needed (unlike the
bad-news screener's LLM step): this is pure arithmetic over data already
in memory, so it can just re-run on every click.

Two-step UI, same shape as the other screener pages:

1. Screen: `data.transforms.valuation_dispersion.screen_valuation_dispersion`
   z-scores each ticker's valuation multiples against its peer group
   (GICS sub-industry by default, or DBSCAN cluster label), crosses that
   against a quality z-score (ROE, margin, leverage), and returns tickers
   whose valuation is a statistical outlier -- split into four signals
   (cheap/expensive x quality-backed/not) rather than one ranked "cheapest"
   list. See that module's docstring for the full rationale.
2. Inspect: clicking a row shows the ticker's own metric values against
   its peer group's median, so the "why" behind the z-score is visible,
   not just the number.
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import dash_table, dcc, html
from dash.dependencies import Input, Output, State

from src.peer_comparison_tool.data.transforms.valuation_dispersion import (
    DEFAULT_VALUATION_METRICS,
    SIGNAL_DESCRIPTIONS,
    screen_valuation_dispersion,
)

from .styles import colors

SUMMARY_COLUMNS = ["ticker", "name", "group", "signal", "valuation_zscore", "quality_zscore", "valuation_peer_group_size"]
SUMMARY_COLUMN_LABELS = {
    "ticker": "Ticker",
    "name": "Name",
    "group": "Peer Group",
    "signal": "Signal",
    "valuation_zscore": "Valuation Z-score",
    "quality_zscore": "Quality Z-score",
    "valuation_peer_group_size": "Peers Used",
}
SIGNAL_LABELS = {
    "cheap_quality_intact": "Cheap, quality intact",
    "cheap_quality_weak": "Cheap, quality weak (possible value trap)",
    "expensive_quality_strong": "Expensive, quality strong",
    "expensive_quality_weak": "Expensive, quality weak (possible overvaluation)",
}
GROUP_COLUMN_OPTIONS = [
    {"label": "GICS Sub-industry", "value": "sub_industry"},
    {"label": "Valuation Cluster (DBSCAN)", "value": "label"},
]
DEFAULT_GROUP_COL = "sub_industry"
DEFAULT_MIN_GROUP_SIZE = 4
DEFAULT_CHEAP_THRESHOLD = -1.0
DEFAULT_EXPENSIVE_THRESHOLD = 1.0
DETAIL_METRICS = DEFAULT_VALUATION_METRICS + ["return_on_equity", "profit_margin", "debt_to_equity_ratio"]
DETAIL_METRIC_LABELS = {
    "price_eps_ratio": "P/E ratio",
    "enterpriseToEbitda": "EV/EBITDA",
    "price_to_book": "P/B ratio",
    "return_on_equity": "Return on equity",
    "profit_margin": "Profit margin",
    "debt_to_equity_ratio": "Debt-to-equity ratio",
}


def get_valuation_dispersion_page_layout() -> html.Div:
    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Peer Valuation Dispersion Screener", style={"color": colors["text"], "textAlign": "center"}),
                width=10, className="mb-4"),
            dbc.Col(dbc.Button("Return to Home", id="back-to-home", color="primary", className="mb-3"), width=2),
        ], align="center"),

        dbc.Row(
            dbc.Col(
                dbc.Alert(
                    "Exploratory tool only. This flags tickers whose valuation multiples are statistical "
                    "outliers versus their own peer group, crossed against a quality check (returns, margins, "
                    "leverage) so a name isn't flagged as \"cheap\" without noting whether the fundamentals back "
                    "that up. A peer group's mean/std is not a fair-value estimate, and a wide gap can persist "
                    "or widen -- this is not investment advice, use it to flag names worth a closer look.",
                    color="warning", style={"marginBottom": "20px"},
                ), width=12,
            )
        ),

        dbc.Row([
            dbc.Col([
                html.Label("Group tickers by:", style={"color": colors["text"]}),
                dcc.Dropdown(id="valdisp-group-col", options=GROUP_COLUMN_OPTIONS, value=DEFAULT_GROUP_COL,
                             clearable=False, style={"marginBottom": "15px"}),
            ], width=3),
            dbc.Col([
                html.Label("Min. peers per group:", style={"color": colors["text"]}),
                dcc.Input(id="valdisp-min-group-size", type="number", value=DEFAULT_MIN_GROUP_SIZE, min=2, step=1,
                          style={"marginBottom": "15px", "width": "100%"}),
            ], width=2),
            dbc.Col([
                html.Label("Cheap threshold (z ≤):", style={"color": colors["text"]}),
                dcc.Input(id="valdisp-cheap-threshold", type="number", value=DEFAULT_CHEAP_THRESHOLD, step=0.1,
                          style={"marginBottom": "15px", "width": "100%"}),
            ], width=2),
            dbc.Col([
                html.Label("Expensive threshold (z ≥):", style={"color": colors["text"]}),
                dcc.Input(id="valdisp-expensive-threshold", type="number", value=DEFAULT_EXPENSIVE_THRESHOLD, step=0.1,
                          style={"marginBottom": "15px", "width": "100%"}),
            ], width=2),
            dbc.Col([
                html.Label(" ", style={"color": colors["text"], "display": "block"}),
                dbc.Button("Run Screen", id="valdisp-screen-button", color="primary", style={"width": "100%"}),
            ], width=3),
        ], align="end"),

        dbc.Row(dbc.Col(html.Div(id="valdisp-screen-status", style={"color": colors["text"], "margin": "10px 0"}))),

        dbc.Row(
            dbc.Col(
                dbc.Card([
                    dbc.CardHeader("Candidates (click a row for detail)",
                                   style={"color": colors["text"], "backgroundColor": colors["background"]}),
                    dbc.CardBody(
                        dash_table.DataTable(
                            id="valdisp-summary-table",
                            columns=[{"name": SUMMARY_COLUMN_LABELS[c], "id": c} for c in SUMMARY_COLUMNS],
                            data=[],
                            row_selectable="single",
                            sort_action="native",
                            filter_action="native",
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

        dbc.Row(dbc.Col(html.Div(id="valdisp-detail-content"), width=12)),
    ], fluid=True, style={"backgroundColor": colors["background"]})


def register_valuation_dispersion_callback(app: dash.Dash, snapshot_recent_metrics: pd.DataFrame) -> None:
    # Keyed by (ticker, group_col) since a ticker's peer-relative metrics
    # depend on which grouping is currently selected.
    last_results_by_ticker: dict[str, dict] = {}

    @app.callback(
        [Output("valdisp-summary-table", "data"), Output("valdisp-screen-status", "children")],
        [Input("valdisp-screen-button", "n_clicks")],
        [
            State("valdisp-group-col", "value"),
            State("valdisp-min-group-size", "value"),
            State("valdisp-cheap-threshold", "value"),
            State("valdisp-expensive-threshold", "value"),
        ],
    )
    def run_screen(n_clicks, group_col, min_group_size, cheap_threshold, expensive_threshold):
        if not n_clicks:
            return [], "Click \"Run Screen\" to screen all tracked tickers against their peers."

        group_col = group_col or DEFAULT_GROUP_COL
        if group_col not in snapshot_recent_metrics.columns:
            return [], f"'{group_col}' isn't available in the loaded data yet."

        results = screen_valuation_dispersion(
            snapshot_recent_metrics,
            group_col=group_col,
            min_group_size=min_group_size or DEFAULT_MIN_GROUP_SIZE,
            cheap_threshold=cheap_threshold if cheap_threshold is not None else DEFAULT_CHEAP_THRESHOLD,
            expensive_threshold=expensive_threshold if expensive_threshold is not None else DEFAULT_EXPENSIVE_THRESHOLD,
        )

        last_results_by_ticker.clear()
        last_results_by_ticker.update({r["ticker"]: {**r, "group_col": group_col} for r in results})

        if not results:
            return [], "No statistically significant valuation outliers found with the current settings."

        rows = [_format_summary_row(r, group_col) for r in results]
        n_groups = snapshot_recent_metrics[group_col].nunique()
        status = f"Screened {len(snapshot_recent_metrics)} tickers across {n_groups} peer groups: {len(results)} flagged."
        return rows, status

    @app.callback(
        Output("valdisp-detail-content", "children"),
        [Input("valdisp-summary-table", "derived_virtual_data"), Input("valdisp-summary-table", "derived_virtual_selected_rows")],
    )
    def show_detail(table_data, selected_rows):
        if not table_data or not selected_rows:
            return html.Div()

        row = table_data[selected_rows[0]]
        ticker = row["ticker"]
        result = last_results_by_ticker.get(ticker)
        if result is None:
            return html.Div("Detail unavailable -- re-run the screen.", style={"color": colors["text"]})

        return _build_detail_layout(result)


def _format_summary_row(result: dict, group_col: str) -> dict:
    return {
        "ticker": result["ticker"],
        "name": result.get("name", ""),
        "group": result.get(group_col, ""),
        "signal": SIGNAL_LABELS.get(result["signal"], result["signal"]),
        "valuation_zscore": round(result["valuation_zscore"], 2),
        "quality_zscore": round(result["quality_zscore"], 2),
        "valuation_peer_group_size": result["valuation_peer_group_size"],
    }


def _build_detail_layout(result: dict) -> html.Div:
    ticker = result["ticker"]
    group_col = result["group_col"]
    peer_group_name = result.get(group_col, "peers")

    metric_rows = []
    for metric in DETAIL_METRICS:
        if metric not in result:
            continue
        zscore = result.get(f"{metric}_zscore")
        value = result.get(metric)
        if pd.isna(value) if value is not None else True:
            continue
        zscore_text = "n/a (excluded/insufficient peers)" if pd.isna(zscore) else f"{zscore:+.2f}σ vs peers"
        metric_rows.append(html.Li(f"{DETAIL_METRIC_LABELS.get(metric, metric)}: {value:.2f} ({zscore_text})",
                                    style={"color": colors["text"]}))

    return dbc.Card([
        dbc.CardHeader(f"{ticker} vs {peer_group_name}",
                       style={"color": colors["text"], "backgroundColor": colors["background"]}),
        dbc.CardBody([
            html.P(SIGNAL_DESCRIPTIONS.get(result["signal"], ""), style={"color": colors["text"]}),
            html.P(f"Composite valuation z-score: {result['valuation_zscore']:+.2f}  |  "
                   f"Composite quality z-score: {result['quality_zscore']:+.2f}  |  "
                   f"Peer group size: {result['valuation_peer_group_size']}",
                   style={"color": colors["text"], "fontWeight": "bold"}),
            html.Ul(metric_rows),
        ], style={"backgroundColor": colors["background"]}),
    ], style={"backgroundColor": colors["background"]})
