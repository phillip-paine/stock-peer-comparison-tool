"""
Market conditions page: a snapshot of current/recent macro conditions.

Three independent sections, each degrading gracefully if its data source
isn't available rather than one missing piece blanking the whole page:

1. **Macro moves** -- 1-day/1-week/1-month % change for every tracked
   non-stock asset (commodities, indices, ETFs, FX, and now Treasury
   yields -- see the new `"rate"` group in `constants.ASSET_CLASS_TICKERS`),
   from the same `AssetClassTimeSeries` table the landing page already
   charts (`data/transforms/market_conditions.compute_asset_moves`). No
   new data, no live calls -- reads from what's already loaded at startup.
2. **Market news** -- a plain, deduped headline list (no LLM summarization,
   per Phillip's call) fetched live, on demand, from a small basket of
   benchmark tickers (`NEWS_BASKET_TICKERS`) via the same
   `YFinanceClient.fetch_news()` the bad-news screener uses.
3. **Economic releases** -- latest-vs-prior for the FRED starter series
   (CPI, JOLTS, payrolls, unemployment, Fed funds -- see
   `data/transforms/economic_releases.FRED_SERIES`), read from
   `EconomicReleaseData` (materialized by `pipeline.ingest_economic_releases`,
   which is a no-op if `FRED_API_KEY` isn't configured -- see that
   function's docstring). Empty rather than absent if that's the case; the
   page says so plainly instead of rendering a confusing blank table.

Coloring convention, both here and for the FRED table: green = up, red =
down -- a plain directional cue (matching how every finance app colors a
price move), not a claim that up is "good" and down is "bad". Whether a
stronger dollar, a rising 10-year yield, or a hotter CPI print is good or
bad news depends entirely on what else is going on and who's asking --
genuinely different from `report_comparison.py`'s
`INVERTED_COLOR_METRICS`, where "lower leverage is healthier" is a fairly
uncontroversial call about one company. Macro data doesn't get that same
treatment here.
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import dash_table, html
from dash.dependencies import Input, Output

from src.peer_comparison_tool.data.clients.yfinance_client import DataRetrievalError, YFinanceClient
from src.peer_comparison_tool.data.transforms.economic_releases import build_release_summary
from src.peer_comparison_tool.data.transforms.market_conditions import compute_asset_moves
from src.peer_comparison_tool.data.transforms.news_headlines import dedupe_headlines

from .styles import colors

# Benchmark tickers polled for "what's driving markets" headlines -- broad
# market (SPY), volatility/fear gauge (^VIX), and the 10-year yield (^TNX,
# rate-sensitive news tends to cluster here) -- not meant to be
# comprehensive news coverage, just a reasonable macro-flavored basket.
NEWS_BASKET_TICKERS = ["SPY", "^VIX", "^TNX"]

MOVES_COLUMNS = ["ticker", "asset_class", "latest_price", "change_1d", "change_1w", "change_1m"]
MOVES_COLUMN_LABELS = {
    "ticker": "Asset", "asset_class": "Class", "latest_price": "Latest",
    "change_1d": "1D", "change_1w": "1W", "change_1m": "1M",
}
RELEASE_COLUMNS = ["name", "prior_date", "prior_value", "latest_date", "latest_value", "change_pct"]
RELEASE_COLUMN_LABELS = {
    "name": "Release", "prior_date": "Prior Period", "prior_value": "Prior",
    "latest_date": "Latest Period", "latest_value": "Latest", "change_pct": "Change",
}
UP_COLOR = "#55efc4"
DOWN_COLOR = "#d63031"


def _change_style(color_column: str, value_column: str) -> list[dict]:
    """`style_data_conditional` rules coloring `value_column` by the sign
    of the underlying (unformatted) numeric value in `color_column` --
    the displayed column holds a formatted string ("+1.2%"), so the sign
    check happens on a parallel hidden numeric field instead of trying to
    parse the display string back into a number."""
    return [
        {"if": {"filter_query": f"{{{color_column}}} > 0", "column_id": value_column}, "color": UP_COLOR},
        {"if": {"filter_query": f"{{{color_column}}} < 0", "column_id": value_column}, "color": DOWN_COLOR},
    ]


def get_market_conditions_page_layout() -> html.Div:
    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Market Conditions", style={"color": colors["text"], "textAlign": "center"}),
                width=10, className="mb-4"),
            dbc.Col(dbc.Button("Return to Home", id="back-to-home", color="primary", className="mb-3"), width=2),
        ], align="center"),

        dbc.Row(
            dbc.Col(
                dbc.Alert(
                    "A snapshot, not a forecast. Macro moves and the news digest below reflect a small "
                    "tracked universe and a handful of benchmark tickers, not comprehensive market coverage. "
                    "Green/red indicates direction (up/down) only -- not a judgement about whether that "
                    "direction is good or bad news, which depends on context this page doesn't attempt to judge.",
                    color="warning", style={"marginBottom": "20px"},
                ), width=12,
            )
        ),

        dbc.Row(
            dbc.Col(
                dbc.Card([
                    dbc.CardHeader("Macro Moves", style={"color": colors["text"], "backgroundColor": colors["background"]}),
                    dbc.CardBody(html.Div(id="marketcond-moves-table"), style={"backgroundColor": colors["background"]}),
                ], style={"backgroundColor": colors["background"], "marginBottom": "20px"}),
                width=12,
            )
        ),

        dbc.Row(
            dbc.Col(
                dbc.Card([
                    dbc.CardHeader([
                        html.Span("Market News", style={"marginRight": "15px"}),
                        dbc.Button("Refresh Headlines", id="marketcond-news-button", size="sm", color="secondary"),
                    ], style={"color": colors["text"], "backgroundColor": colors["background"]}),
                    dbc.CardBody(html.Div(id="marketcond-news-content"), style={"backgroundColor": colors["background"]}),
                ], style={"backgroundColor": colors["background"], "marginBottom": "20px"}),
                width=12,
            )
        ),

        dbc.Row(
            dbc.Col(
                dbc.Card([
                    dbc.CardHeader("Economic Releases (FRED)", style={"color": colors["text"], "backgroundColor": colors["background"]}),
                    dbc.CardBody(html.Div(id="marketcond-releases-table"), style={"backgroundColor": colors["background"]}),
                ], style={"backgroundColor": colors["background"]}),
                width=12,
            )
        ),
    ], fluid=True, style={"backgroundColor": colors["background"]})


def register_market_conditions_callback(
    app: dash.Dash,
    economic_data: pd.DataFrame,
    economic_release_data: pd.DataFrame,
) -> None:
    yfinance_client = YFinanceClient()

    @app.callback(Output("marketcond-moves-table", "children"), [Input("marketcond-moves-table", "id")])
    def render_moves_table(_):
        moves = compute_asset_moves(economic_data)
        if not moves:
            return html.P("No asset-class data available.", style={"color": colors["text"]})

        rows = [_format_moves_row(m) for m in moves]
        rows.sort(key=lambda r: (r["asset_class"], r["ticker"]))
        return dash_table.DataTable(
            columns=[{"name": MOVES_COLUMN_LABELS[c], "id": c} for c in MOVES_COLUMNS],
            data=rows, sort_action="native", filter_action="native",
            style_header={"backgroundColor": colors["background"], "color": colors["text"], "fontWeight": "bold"},
            style_data={"backgroundColor": colors["background"], "color": colors["text"]},
            style_cell={"minWidth": "90px", "textAlign": "left"},
            style_data_conditional=(
                _change_style("_1d_raw", "change_1d") + _change_style("_1w_raw", "change_1w")
                + _change_style("_1m_raw", "change_1m")
            ),
        )

    @app.callback(Output("marketcond-news-content", "children"), [Input("marketcond-news-button", "n_clicks")])
    def render_news(n_clicks):
        if not n_clicks:
            return html.P("Click \"Refresh Headlines\" to pull the latest market news.", style={"color": colors["text"]})

        news_by_source = {}
        for ticker in NEWS_BASKET_TICKERS:
            try:
                news_by_source[ticker] = yfinance_client.fetch_news(ticker)
            except DataRetrievalError:
                news_by_source[ticker] = []

        headlines = dedupe_headlines(news_by_source)
        if not headlines:
            return html.P("No headlines available right now.", style={"color": colors["text"]})

        return html.Ul([_render_headline(h) for h in headlines])

    @app.callback(Output("marketcond-releases-table", "children"), [Input("marketcond-releases-table", "id")])
    def render_releases_table(_):
        if economic_release_data.empty:
            return html.P(
                "No economic release data available -- requires a FRED_API_KEY to be configured "
                "and the pipeline to have run (see pipeline.ingest_economic_releases).",
                style={"color": colors["text"]},
            )

        observations_by_series = {
            series_id: group.sort_values("date")[["date", "value"]]
            for series_id, group in economic_release_data.groupby("series_id")
        }
        summary = build_release_summary(observations_by_series)
        if not summary:
            return html.P("No economic release data available.", style={"color": colors["text"]})

        rows = [_format_release_row(r) for r in summary]
        return dash_table.DataTable(
            columns=[{"name": RELEASE_COLUMN_LABELS[c], "id": c} for c in RELEASE_COLUMNS],
            data=rows, sort_action="native",
            style_header={"backgroundColor": colors["background"], "color": colors["text"], "fontWeight": "bold"},
            style_data={"backgroundColor": colors["background"], "color": colors["text"]},
            style_cell={"minWidth": "100px", "textAlign": "left"},
            style_data_conditional=_change_style("_change_raw", "change_pct"),
        )


def _format_moves_row(move: dict) -> dict:
    def fmt_pct(v):
        return "n/a" if v is None else f"{v * 100:+.1f}%"

    return {
        "ticker": move["ticker"],
        "asset_class": move["asset_class"],
        "latest_price": f"{move['latest_price']:,.2f}",
        "change_1d": fmt_pct(move["change_1d"]),
        "change_1w": fmt_pct(move["change_1w"]),
        "change_1m": fmt_pct(move["change_1m"]),
        "_1d_raw": move["change_1d"] or 0,
        "_1w_raw": move["change_1w"] or 0,
        "_1m_raw": move["change_1m"] or 0,
    }


def _format_release_row(release: dict) -> dict:
    change_pct = release["change_pct"]
    return {
        "name": release["name"],
        "prior_date": str(release["prior_date"]) if release["prior_date"] else "n/a",
        "prior_value": "n/a" if release["prior_value"] is None else f"{release['prior_value']:,.2f}",
        "latest_date": str(release["latest_date"]),
        "latest_value": f"{release['latest_value']:,.2f}",
        "change_pct": "n/a" if change_pct is None else f"{change_pct * 100:+.1f}%",
        "_change_raw": change_pct or 0,
    }


def _render_headline(headline: dict) -> html.Li:
    also_from = f" (also: {', '.join(headline['also_from'])})" if headline["also_from"] else ""
    label = f"{headline['title']} — {headline['source']}{also_from}"
    if headline.get("link"):
        content = html.A(label, href=headline["link"], target="_blank", style={"color": colors["text"]})
    else:
        content = label
    return html.Li(content, style={"color": colors["text"], "marginBottom": "6px"})
