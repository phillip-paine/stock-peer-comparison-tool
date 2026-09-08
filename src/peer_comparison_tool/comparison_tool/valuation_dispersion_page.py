"""
Peer valuation dispersion screener page.

On-demand, computed entirely from `snapshot_recent_metrics` -- the same
frame `comparison_page.py` already uses, loaded once at dashboard startup
(see `data_loader.py`). No network calls, no caching needed (unlike the
bad-news screener's LLM step): this is pure arithmetic over data already
in memory, so it can just re-run on every click.

Two-step UI, same shape as the other screener pages:

1. Screen: `data.transforms.valuation_dispersion.score_valuation_dispersion`
   z-scores each ticker's valuation multiples against its peer group
   (GICS sub-industry by default, or DBSCAN cluster label), crosses that
   against a quality z-score (ROE, margin, leverage), and classifies every
   ticker -- flagged ones drive the summary table, and the full set
   (flagged and not) drives the quadrant map below it.
2. Inspect: clicking a row shows the ticker's own metric values against
   its peer group's median, so the "why" behind the z-score is visible,
   not just the number.
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import dash_table, dcc, html
from dash.dependencies import Input, Output, State

from src.peer_comparison_tool.data.transforms.valuation_dispersion import (
    CHEAP_QUALITY_INTACT,
    CHEAP_QUALITY_WEAK,
    DEFAULT_VALUATION_METRICS,
    EXPENSIVE_QUALITY_STRONG,
    EXPENSIVE_QUALITY_WEAK,
    NO_SIGNAL,
    SIGNAL_DESCRIPTIONS,
    score_valuation_dispersion,
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
    NO_SIGNAL: "No signal (inside thresholds)",
}
SIGNAL_COLORS = {
    CHEAP_QUALITY_INTACT: "#55efc4",       # green -- the "buy idea" quadrant
    CHEAP_QUALITY_WEAK: "#fdcb6e",         # amber -- possible value trap
    EXPENSIVE_QUALITY_STRONG: "#74b9ff",   # blue -- priced for quality
    EXPENSIVE_QUALITY_WEAK: "#d63031",     # red -- possible overvaluation
    NO_SIGNAL: "#636e72",                  # muted gray -- the middle gap
}
# Fixed legend/plot order so the four quadrants + gap always appear in the
# same order regardless of which signals happen to be present in the data.
SIGNAL_ORDER = [CHEAP_QUALITY_INTACT, EXPENSIVE_QUALITY_STRONG, CHEAP_QUALITY_WEAK, EXPENSIVE_QUALITY_WEAK, NO_SIGNAL]
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
                    dbc.CardHeader("Quadrant Map (valuation vs. quality, both vs. peer group)",
                                   style={"color": colors["text"], "backgroundColor": colors["background"]}),
                    dbc.CardBody(
                        dcc.Graph(id="valdisp-quadrant-chart", style={"height": "65vh"}),
                        style={"backgroundColor": colors["background"]},
                    ),
                ], style={"backgroundColor": colors["background"], "marginBottom": "20px"}),
                width=12,
            )
        ),

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
        [
            Output("valdisp-summary-table", "data"),
            Output("valdisp-screen-status", "children"),
            Output("valdisp-quadrant-chart", "figure"),
        ],
        [Input("valdisp-screen-button", "n_clicks")],
        [
            State("valdisp-group-col", "value"),
            State("valdisp-min-group-size", "value"),
            State("valdisp-cheap-threshold", "value"),
            State("valdisp-expensive-threshold", "value"),
        ],
    )
    def run_screen(n_clicks, group_col, min_group_size, cheap_threshold, expensive_threshold):
        empty_fig = _empty_quadrant_figure()
        if not n_clicks:
            return [], "Click \"Run Screen\" to screen all tracked tickers against their peers.", empty_fig

        group_col = group_col or DEFAULT_GROUP_COL
        if group_col not in snapshot_recent_metrics.columns:
            return [], f"'{group_col}' isn't available in the loaded data yet.", empty_fig

        min_group_size = min_group_size or DEFAULT_MIN_GROUP_SIZE
        cheap_threshold = cheap_threshold if cheap_threshold is not None else DEFAULT_CHEAP_THRESHOLD
        expensive_threshold = expensive_threshold if expensive_threshold is not None else DEFAULT_EXPENSIVE_THRESHOLD

        scored = score_valuation_dispersion(
            snapshot_recent_metrics, group_col=group_col, min_group_size=min_group_size,
            cheap_threshold=cheap_threshold, expensive_threshold=expensive_threshold,
        )
        if scored.empty:
            return [], "No data available to screen.", empty_fig

        # Points with no valuation z-score at all (peer group too thin for
        # every metric) can't be placed on the map -- drop just those from
        # the chart rather than plotting them at a meaningless position.
        plottable = scored.dropna(subset=["valuation_zscore"])
        fig = _build_quadrant_figure(plottable, group_col, cheap_threshold, expensive_threshold)

        results = scored[scored["signal"] != NO_SIGNAL].copy()
        results["_sort_key"] = results["valuation_zscore"].abs()
        results = results.sort_values("_sort_key", ascending=False).drop(columns="_sort_key")
        results_records = results.to_dict("records")

        last_results_by_ticker.clear()
        last_results_by_ticker.update({r["ticker"]: {**r, "group_col": group_col} for r in results_records})

        if not results_records:
            status = "No statistically significant valuation outliers found with the current settings."
        else:
            n_groups = snapshot_recent_metrics[group_col].nunique()
            status = f"Screened {len(snapshot_recent_metrics)} tickers across {n_groups} peer groups: {len(results_records)} flagged."

        rows = [_format_summary_row(r, group_col) for r in results_records]
        return rows, status, fig

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


def _empty_quadrant_figure() -> "px.scatter":
    fig = px.scatter(title="Run the screen to plot tickers")
    fig.update_layout(plot_bgcolor=colors["background"], paper_bgcolor=colors["background"],
                       font_color=colors["text"], margin=dict(l=20, r=20, t=30, b=20))
    return fig


def _build_quadrant_figure(scored: pd.DataFrame, group_col: str, cheap_threshold: float, expensive_threshold: float):
    """Valuation (x) vs. quality (y) scatter, one dot per ticker, colored by
    signal -- the four flagged quadrants plus a muted gray for `NO_SIGNAL`
    tickers sitting in the gap between the cheap/expensive thresholds.

    Unlike a standard quadrant map split down the middle, there's a real
    vertical band here (shaded, between `cheap_threshold` and
    `expensive_threshold`) where a ticker doesn't get classified either
    way regardless of its quality score -- that band, and the `NO_SIGNAL`
    dots inside it, are the point: most tickers' valuation isn't a
    statistical outlier, and this map should make that visible rather than
    forcing every ticker into one of four boxes.

    Hover detail mirrors the scatter chart on the main comparison page
    (`comparison_page.py`'s `fig3`) -- same metrics, same dark theme.
    """
    present_signals = [s for s in SIGNAL_ORDER if s in scored["signal"].unique()]

    fig = px.scatter(
        scored, x="valuation_zscore", y="quality_zscore", color="signal", text="ticker",
        color_discrete_map=SIGNAL_COLORS, category_orders={"signal": present_signals},
        hover_name="ticker",
        hover_data={
            "signal": False, "valuation_zscore": ":.2f", "quality_zscore": ":.2f",
            "name": True, group_col: True, "market_cap_MM": ":.0f",
            "price_eps_ratio": ":.1f", "enterpriseToEbitda": ":.1f", "price_to_book": ":.1f",
            "return_on_equity": ":.1%", "profit_margin": ":.1%", "debt_to_equity_ratio": ":.2f",
            "valuation_peer_group_size": True,
        },
        labels={
            "valuation_zscore": "Valuation z-score vs. peers (← cheap · expensive →)",
            "quality_zscore": "Quality z-score vs. peers (ROE, margin, leverage) →",
            "signal": "Signal",
        },
        title="Valuation vs. Quality, both scored against each ticker's own peer group",
    )
    fig.update_traces(textposition="top center", marker=dict(size=9, line=dict(width=1, color="DarkSlateGrey")))

    # The "gap" band: no ticker inside it gets a signal regardless of quality.
    fig.add_vrect(x0=cheap_threshold, x1=expensive_threshold, fillcolor=SIGNAL_COLORS[NO_SIGNAL],
                  opacity=0.12, line_width=0, layer="below")
    fig.add_vline(x=cheap_threshold, line_dash="dash", line_color=colors["text"], opacity=0.4)
    fig.add_vline(x=expensive_threshold, line_dash="dash", line_color=colors["text"], opacity=0.4)
    fig.add_hline(y=0, line_dash="dash", line_color=colors["text"], opacity=0.4)

    quadrant_labels = [
        ("Cheap, quality intact", 0.02, 0.98, "left", "top"),
        ("Expensive, quality strong", 0.98, 0.98, "right", "top"),
        ("Cheap, quality weak", 0.02, 0.02, "left", "bottom"),
        ("Expensive, quality weak", 0.98, 0.02, "right", "bottom"),
    ]
    for text, x, y, xanchor, yanchor in quadrant_labels:
        fig.add_annotation(text=text, xref="paper", yref="paper", x=x, y=y, xanchor=xanchor, yanchor=yanchor,
                            showarrow=False, font=dict(size=11, color=colors["text"]), opacity=0.6)

    fig.update_layout(
        plot_bgcolor=colors["background"], paper_bgcolor=colors["background"], font_color=colors["text"],
        margin=dict(l=20, r=20, t=40, b=20), legend_title_text="Signal",
    )
    return fig


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
