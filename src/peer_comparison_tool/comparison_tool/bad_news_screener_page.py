"""
Bad-news price-drop screener page.

On-demand, not pipeline-materialized -- same philosophy as
`pairs_trading_page.py`: click "Screen for Bad News" and the current
top-N-by-market-cap tickers are screened for a recent price-drop pattern
using price history already loaded into the dashboard at startup
(`ticker_series_data`, `snapshot_recent_metrics` -- no yfinance call for
prices). Only the tickers that clear the price-drop screen get a live news
fetch + LLM grade, since that step is the expensive/rate-limited one.

Two-step UI, mirroring the pairs screener:

1. Screen: `data.transforms.bad_news_screener.select_top_by_market_cap` +
   `detect_price_drop_candidates` find price-drop candidates, then
   `comparison_tool.news_sentiment.screen_news_sentiment` fetches each
   candidate's recent headlines and asks an LLM for an investment grade,
   rendered as a sortable summary table (worst grade first).
2. Inspect: clicking a table row shows that ticker's headlines and the
   LLM's summary in a detail panel.

This is a screening/exploratory tool, not a trading signal or investment
advice -- the page says so directly, matching how the pairs-trading and
DCF pages already frame their own caveats. The LLM step needs
`HUGGINGFACE_API_TOKEN` to be set; if it isn't, the page still loads and
the screen button reports that clearly instead of the app failing to
start (see `comparison_tool.constants` for why importing this module
never requires the token).
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import dash_table, dcc, html
from dash.dependencies import Input, Output, State

from src.peer_comparison_tool.data.clients.yfinance_client import DataRetrievalError, YFinanceClient
from src.peer_comparison_tool.data.transforms.bad_news_screener import (
    detect_price_drop_candidates,
    select_top_by_market_cap,
)

from .news_sentiment import NewsSentimentCache, extract_headlines, get_chat_model, screen_news_sentiment
from .styles import colors

SUMMARY_COLUMNS = ["ticker", "reason", "price_drop_pct", "investment_grade", "summary"]
SUMMARY_COLUMN_LABELS = {
    "ticker": "Ticker",
    "reason": "Price Signal",
    "price_drop_pct": "Price Drop (3d vs prior window)",
    "investment_grade": "LLM Investment Grade (1=best, 10=worst)",
    "summary": "LLM Summary",
}
REASON_LABELS = {"fall_from_recent_high": "Fell from recent high", "recent_price_drop": "Recent price drop"}
DEFAULT_TOP_N = 20


def get_bad_news_screener_page_layout() -> html.Div:
    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Bad News Screener", style={"color": colors["text"], "textAlign": "center"}),
                width=10, className="mb-4"),
            dbc.Col(dbc.Button("Return to Home", id="back-to-home", color="primary", className="mb-3"), width=2),
        ], align="center"),

        dbc.Row(
            dbc.Col(
                dbc.Alert(
                    "Exploratory tool only. This screens the largest companies by market cap for a recent "
                    "price-drop pattern, then asks an LLM to grade recent headlines for each candidate. The "
                    "price pattern and the LLM grade are both backward-looking and can be wrong in either "
                    "direction -- this is not investment advice, use it to flag names worth a closer look.",
                    color="warning", style={"marginBottom": "20px"},
                ), width=12,
            )
        ),

        dbc.Row([
            dbc.Col([
                html.Label("Screen the top N tickers by market cap:", style={"color": colors["text"]}),
                dcc.Input(id="bad-news-top-n", type="number", value=DEFAULT_TOP_N, min=1, step=1,
                          style={"marginBottom": "15px", "width": "100%"}),
            ], width=3),
            dbc.Col([
                html.Label(" ", style={"color": colors["text"], "display": "block"}),
                dbc.Button("Screen for Bad News", id="bad-news-screen-button", color="primary",
                           style={"width": "100%"}),
            ], width=3),
        ], align="end"),

        dbc.Row(dbc.Col(html.Div(id="bad-news-screen-status", style={"color": colors["text"], "margin": "10px 0"}))),

        dbc.Row(
            dbc.Col(
                dbc.Card([
                    dbc.CardHeader("Candidates (click a row for headlines)",
                                   style={"color": colors["text"], "backgroundColor": colors["background"]}),
                    dbc.CardBody(
                        dash_table.DataTable(
                            id="bad-news-summary-table",
                            columns=[{"name": SUMMARY_COLUMN_LABELS[c], "id": c} for c in SUMMARY_COLUMNS],
                            data=[],
                            row_selectable="single",
                            sort_action="native",
                            style_header={"backgroundColor": colors["background"], "color": colors["text"], "fontWeight": "bold"},
                            style_data={"backgroundColor": colors["background"], "color": colors["text"]},
                            style_cell={"minWidth": "110px", "whiteSpace": "normal", "textAlign": "left"},
                        ),
                        style={"backgroundColor": colors["background"]},
                    ),
                ], style={"backgroundColor": colors["background"], "marginBottom": "20px"}),
                width=12,
            )
        ),

        dbc.Row(dbc.Col(html.Div(id="bad-news-detail-content"), width=12)),
    ], fluid=True, style={"backgroundColor": colors["background"]})


def register_bad_news_screener_callback(
    app: dash.Dash,
    ticker_series_data: pd.DataFrame,
    snapshot_recent_metrics: pd.DataFrame,
) -> None:
    yfinance_client = YFinanceClient()
    cache = NewsSentimentCache()
    news_by_ticker: dict[str, list[str]] = {}
    # Built lazily on first click, not at app startup, so the dashboard
    # still starts with no HUGGINGFACE_API_TOKEN set (see module docstring).
    llm_holder: dict[str, object] = {}

    def _get_llm():
        if "llm" not in llm_holder:
            llm_holder["llm"] = get_chat_model()
        return llm_holder["llm"]

    @app.callback(
        [Output("bad-news-summary-table", "data"), Output("bad-news-screen-status", "children")],
        [Input("bad-news-screen-button", "n_clicks")],
        [State("bad-news-top-n", "value")],
    )
    def run_screen(n_clicks, top_n):
        if not n_clicks:
            return [], "Click \"Screen for Bad News\" to run the screen."

        top_n = top_n or DEFAULT_TOP_N
        top_tickers = select_top_by_market_cap(snapshot_recent_metrics, top_n=top_n)
        if not top_tickers:
            return [], "No market-cap data available to rank tickers."

        candidates = detect_price_drop_candidates(ticker_series_data, tickers=top_tickers)
        if not candidates:
            return [], f"Screened the top {len(top_tickers)} tickers by market cap; no price-drop candidates found."

        try:
            llm = _get_llm()
        except RuntimeError as exc:
            # Still show the price-only candidates rather than failing outright --
            # the LLM grade is an enrichment, not a precondition for the price signal.
            rows = [_format_summary_row({**c, "investment_grade": None, "summary": None, "error": str(exc)})
                    for c in candidates]
            return rows, f"{len(candidates)} price-drop candidate(s) found. LLM grading unavailable: {exc}"

        for candidate in candidates:
            ticker = candidate["ticker"]
            if ticker in news_by_ticker:
                continue
            try:
                raw_news = yfinance_client.fetch_news(ticker)
                news_by_ticker[ticker] = extract_headlines(raw_news)
            except DataRetrievalError:
                news_by_ticker[ticker] = []

        results = screen_news_sentiment(candidates, news_by_ticker, llm, cache=cache)
        rows = [_format_summary_row(r) for r in results]
        n_graded = sum(1 for r in results if r["investment_grade"] is not None)
        status = f"Screened the top {len(top_tickers)} tickers by market cap: {len(results)} price-drop candidate(s), {n_graded} graded by the LLM."
        return rows, status

    @app.callback(
        Output("bad-news-detail-content", "children"),
        [Input("bad-news-summary-table", "derived_virtual_data"), Input("bad-news-summary-table", "derived_virtual_selected_rows")],
    )
    def show_detail(table_data, selected_rows):
        if not table_data or not selected_rows:
            return html.Div()

        row = table_data[selected_rows[0]]
        ticker = row["ticker"]
        headlines = news_by_ticker.get(ticker, [])

        return dbc.Card([
            dbc.CardHeader(ticker, style={"color": colors["text"], "backgroundColor": colors["background"]}),
            dbc.CardBody([
                html.P(f"LLM summary: {row['summary'] or 'n/a'}", style={"color": colors["text"]}),
                html.P("Recent headlines:", style={"color": colors["text"], "fontWeight": "bold"}),
                html.Ul([html.Li(h, style={"color": colors["text"]}) for h in headlines])
                if headlines else html.P("No headlines available.", style={"color": colors["text"]}),
            ], style={"backgroundColor": colors["background"]}),
        ], style={"backgroundColor": colors["background"]})


def _format_summary_row(result: dict) -> dict:
    price_drop_pct = result.get("price_drop_pct")
    grade = result.get("investment_grade")
    return {
        "ticker": result["ticker"],
        "reason": REASON_LABELS.get(result.get("reason"), result.get("reason") or "n/a"),
        "price_drop_pct": "n/a" if price_drop_pct is None else f"{price_drop_pct * 100:.1f}%",
        "investment_grade": "n/a" if grade is None else round(grade, 1),
        "summary": result.get("summary") or (result.get("error") or "n/a"),
    }
