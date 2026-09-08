"""
Report comparison page: latest vs. prior period, one ticker at a time.

Distinct from `company_quarterly_report_page.py` (which charts one metric
over time across many tickers) -- this is a snapshot table for a single
ticker: pick quarterly or annual, tick which metrics to show, see
latest value / prior value / % change side by side, plus a link out to
that ticker's SEC filings.

Metric list is fixed (drawn from `report_comparison.QUARTERLY_METRIC_LABELS`
/ `ANNUAL_METRIC_LABELS`, which mirror what's actually persisted in
`quarterly_financial_data` / `balance_sheet_data` / `cashflow_statement_data`)
-- "add/remove" here means toggling which of those already-available
metrics are shown, via a checklist, not pulling in arbitrary new fields.
See `report_comparison.py`'s module docstring for why balance-sheet/
cashflow are annual-only today.

SEC link is the "easy version": a direct link to EDGAR's own company
filings search, pre-filled with the ticker and filtered to the right form
type (10-Q for quarterly, 10-K for annual) -- not a lookup of the specific
latest filing (that would need resolving ticker -> CIK via SEC's official
mapping and is a reasonable step 2, not built here).
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import dash_table, dcc, html
from dash.dependencies import Input, Output, State

from src.peer_comparison_tool.data.transforms.report_comparison import (
    ANNUAL_METRIC_LABELS,
    LARGE_NUMBER_METRICS,
    PERCENT_METRICS,
    QUARTERLY_METRIC_LABELS,
    build_annual_frame,
    build_comparison_table,
)

from .styles import colors

QUARTERLY = "quarterly"
ANNUAL = "annual"

PERIOD_TYPE_OPTIONS = [
    {"label": "Quarterly", "value": QUARTERLY},
    {"label": "Annual", "value": ANNUAL},
]
METRIC_LABELS_BY_PERIOD = {QUARTERLY: QUARTERLY_METRIC_LABELS, ANNUAL: ANNUAL_METRIC_LABELS}
PERIOD_COL_BY_PERIOD = {QUARTERLY: "quarter_reporting", ANNUAL: "annual_reporting"}
SEC_FORM_TYPE_BY_PERIOD = {QUARTERLY: "10-Q", ANNUAL: "10-K"}

TABLE_COLUMNS = ["metric", "prior_period", "prior_value", "latest_period", "latest_value", "change_pct"]
TABLE_COLUMN_LABELS = {
    "metric": "Metric",
    "prior_period": "Prior Period",
    "prior_value": "Prior",
    "latest_period": "Latest Period",
    "latest_value": "Latest",
    "change_pct": "Change",
}


def _sec_edgar_url(ticker: str, form_type: str) -> str:
    """EDGAR's own company-filings search, pre-filled with the ticker and
    filtered to `form_type` -- see module docstring on why this is the
    "easy version" of the SEC link, not a resolved link to one filing."""
    return (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&company={ticker}&type={form_type}&dateb=&owner=include&count=40"
    )


def get_report_comparison_page_layout(company_info: pd.DataFrame) -> html.Div:
    tickers = sorted(company_info["ticker"].unique())
    default_ticker = tickers[0] if tickers else None

    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Report Comparison: Latest vs. Prior Period", style={"color": colors["text"], "textAlign": "center"}),
                width=10, className="mb-4"),
            dbc.Col(dbc.Button("Return to Home", id="back-to-home", color="primary", className="mb-3"), width=2),
        ], align="center"),

        dbc.Row([
            dbc.Col([
                html.Label("Ticker:", style={"color": colors["text"]}),
                dcc.Dropdown(id="reportcmp-ticker", options=[{"label": t, "value": t} for t in tickers],
                             value=default_ticker, clearable=False, style={"marginBottom": "15px"}),
            ], width=3),
            dbc.Col([
                html.Label("Period:", style={"color": colors["text"]}),
                dcc.RadioItems(id="reportcmp-period-type", options=PERIOD_TYPE_OPTIONS, value=QUARTERLY,
                               inline=True, labelStyle={"color": colors["text"], "marginRight": "15px"}),
            ], width=3),
            dbc.Col([
                html.A(dbc.Button("View SEC Filings ↗", color="secondary", style={"width": "100%"}),
                       id="reportcmp-sec-link", href="#", target="_blank"),
            ], width=3, align="end"),
        ], align="end", className="mb-3"),

        dbc.Row([
            dbc.Col([
                html.Label("Metrics to show:", style={"color": colors["text"]}),
                dcc.Checklist(id="reportcmp-metric-checklist", inline=False,
                              labelStyle={"color": colors["text"], "display": "block"}),
            ], width=3),
            dbc.Col(
                dbc.Card([
                    dbc.CardHeader(id="reportcmp-table-header",
                                   style={"color": colors["text"], "backgroundColor": colors["background"]}),
                    dbc.CardBody(
                        dash_table.DataTable(
                            id="reportcmp-table",
                            columns=[{"name": TABLE_COLUMN_LABELS[c], "id": c} for c in TABLE_COLUMNS],
                            data=[],
                            style_header={"backgroundColor": colors["background"], "color": colors["text"], "fontWeight": "bold"},
                            style_data={"backgroundColor": colors["background"], "color": colors["text"]},
                            style_cell={"minWidth": "100px", "textAlign": "left"},
                        ),
                        style={"backgroundColor": colors["background"]},
                    ),
                ], style={"backgroundColor": colors["background"]}),
                width=9,
            ),
        ]),
    ], fluid=True, style={"backgroundColor": colors["background"]})


def register_report_comparison_callback(
    app: dash.Dash,
    qfin_data: pd.DataFrame,
    bs_data: pd.DataFrame,
    cashflow_map: dict[str, pd.DataFrame],
) -> None:
    @app.callback(
        [Output("reportcmp-metric-checklist", "options"), Output("reportcmp-metric-checklist", "value")],
        [Input("reportcmp-period-type", "value")],
    )
    def update_metric_options(period_type):
        labels = METRIC_LABELS_BY_PERIOD.get(period_type, {})
        options = [{"label": label, "value": metric} for metric, label in labels.items()]
        return options, list(labels.keys())  # default: everything ticked

    @app.callback(Output("reportcmp-sec-link", "href"), [Input("reportcmp-ticker", "value"), Input("reportcmp-period-type", "value")])
    def update_sec_link(ticker, period_type):
        if not ticker:
            return "#"
        return _sec_edgar_url(ticker, SEC_FORM_TYPE_BY_PERIOD.get(period_type, "10-Q"))

    @app.callback(
        [Output("reportcmp-table", "data"), Output("reportcmp-table-header", "children")],
        [
            Input("reportcmp-ticker", "value"),
            Input("reportcmp-period-type", "value"),
            Input("reportcmp-metric-checklist", "value"),
        ],
    )
    def update_table(ticker, period_type, selected_metrics):
        if not ticker or not period_type:
            return [], ""

        if period_type == QUARTERLY:
            source_df = qfin_data
        else:
            source_df = build_annual_frame(bs_data, cashflow_map, ticker)

        metrics = selected_metrics or list(METRIC_LABELS_BY_PERIOD.get(period_type, {}).keys())
        rows = build_comparison_table(source_df, ticker, metrics, period_col=PERIOD_COL_BY_PERIOD[period_type])

        header = f"{ticker} -- {'Quarterly' if period_type == QUARTERLY else 'Annual'} metrics"
        if not rows:
            return [], f"{header} (no data available for this ticker)"

        labels = METRIC_LABELS_BY_PERIOD[period_type]
        table_rows = [_format_table_row(r, labels) for r in rows]
        return table_rows, header


def _format_table_row(row: dict, labels: dict[str, str]) -> dict:
    metric = row["metric"]
    is_percent = metric in PERCENT_METRICS
    is_large_number = metric in LARGE_NUMBER_METRICS
    return {
        "metric": labels.get(metric, metric),
        "prior_period": row["prior_period"] or "n/a",
        "prior_value": _format_value(row["prior_value"], is_percent, is_large_number),
        "latest_period": row["latest_period"] or "n/a",
        "latest_value": _format_value(row["latest_value"], is_percent, is_large_number),
        "change_pct": "n/a" if row["change_pct"] is None else f"{row['change_pct'] * 100:+.1f}%",
    }


def _format_value(value, is_percent: bool, is_large_number: bool) -> str:
    """Formats by metric category (see `LARGE_NUMBER_METRICS`/`PERCENT_METRICS`
    docstrings for why this doesn't branch on the value's Python type)."""
    if value is None:
        return "n/a"
    numeric = float(value)
    if is_percent:
        return f"{numeric * 100:.1f}%"
    if is_large_number:
        return f"{numeric:,.0f}"
    return f"{numeric:,.2f}"
