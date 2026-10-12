"""
Market conditions page: a snapshot of current/recent macro conditions.

Independent sections, each degrading gracefully if its data source isn't
available rather than one missing piece blanking the whole page:

1. **Macro moves** -- 1-day/1-week/1-month % change for every tracked
   non-stock asset (commodities, indices, ETFs, FX, and Treasury yields --
   see the `"rate"` group in `constants.ASSET_CLASS_TICKERS`), from the same
   `AssetClassTimeSeries` table the landing page already charts
   (`data/transforms/market_conditions.compute_asset_moves`). No new data, no
   live calls -- reads from what's already loaded at startup.
2. **FRED-backed sections** -- Rates & Curve (10Y/2Y/3M yields, the 2s10s
   spread, fed funds and target range), Rate Expectations (the FOMC's own
   median projections plus market-leaning proxies), Labor Market (payrolls,
   unemployment, JOLTS, jobless claims, wages) and Inflation (CPI, core CPI,
   core PCE). Series catalog, units and the summary maths live in
   `data/transforms/economic_releases.py`; the data is read from
   `EconomicReleaseData` (materialized by `pipeline.ingest_economic_releases`,
   a no-op without `FRED_API_KEY`). Each section shows an explicit "no FRED
   data" message when its series aren't there, rather than a confusing blank.

   Two honesty points the page states in-line: the FOMC projections are the
   Fed's own view, not market pricing; and the "market-leaning" rows are
   Treasury-yield proxies, not fed-funds-futures probabilities (which FRED
   doesn't carry).
3. **Market news** -- a plain, deduped headline list (no LLM summarization)
   fetched live, on demand, from a small basket of benchmark tickers
   (`NEWS_BASKET_TICKERS`) via the same `YFinanceClient.fetch_news()` the
   bad-news screener uses.

Charts follow a Financial Times house style (pale paper background,
left-aligned title, horizontal gridlines only, FT palette, text a size up from
Plotly's default). The tables stay in the app's dark theme.

Coloring convention, both here and for the FRED tables: green = up, red =
down -- a plain directional cue (matching how every finance app colors a
price move), not a claim that up is "good" and down is "bad". Whether a
stronger dollar, a rising 10-year yield, or a hotter CPI print is good or
bad news depends entirely on what else is going on and who's asking --
genuinely different from `report_comparison.py`'s `INVERTED_COLOR_METRICS`,
where "lower leverage is healthier" is a fairly uncontroversial call about
one company. Macro data doesn't get that same treatment here.
"""
from __future__ import annotations

import logging
from datetime import date

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dash_table, dcc, html
from dash.dependencies import Input, Output

from src.peer_comparison_tool.data.clients.yfinance_client import DataRetrievalError, YFinanceClient
from src.peer_comparison_tool.data.transforms.economic_releases import (
    NOISE_BAND_BP, build_market_proxies, build_release_summary, build_sep_table, current_policy_rate,
    format_change, format_level, format_yoy, spec_for,
)
from src.peer_comparison_tool.data.transforms.market_conditions import compute_asset_moves
from src.peer_comparison_tool.data.transforms.news_headlines import dedupe_headlines

from .styles import colors

logger = logging.getLogger(__name__)

# Benchmark tickers polled for "what's driving markets" headlines -- broad
# market (SPY), volatility/fear gauge (^VIX), and the 10-year yield (^TNX,
# rate-sensitive news tends to cluster here) -- not meant to be
# comprehensive news coverage, just a reasonable macro-flavored basket.
NEWS_BASKET_TICKERS = ["SPY", "QQQ", "TLT", "^VIX", "^TNX"]

MOVES_COLUMNS = ["ticker", "asset_class", "latest_price", "change_1d", "change_1w", "change_1m"]
MOVES_COLUMN_LABELS = {
    "ticker": "Asset", "asset_class": "Class", "latest_price": "Latest",
    "change_1d": "1D", "change_1w": "1W", "change_1m": "1M",
}
RELEASE_COLUMNS = ["name", "latest_date", "latest", "prior", "change"]
RELEASE_COLUMN_LABELS = {
    "name": "Series", "latest_date": "As of", "latest": "Latest", "prior": "Prior",
    "change": "Change", "yoy": "YoY",
}
SEP_COLUMNS = [{"name": "Projection", "id": "label"}, {"name": "FOMC median", "id": "median"},
               {"name": "vs current", "id": "vs_current"}]
PROXY_COLUMNS = [{"name": "Proxy", "id": "name"}, {"name": "Yield", "id": "yield_"},
                 {"name": "Fed funds", "id": "policy_rate"}, {"name": "Gap", "id": "gap"},
                 {"name": "Reading", "id": "reading"}, {"name": "As of", "id": "as_of"}]

NO_FRED_MESSAGE = (
    "No FRED data in the database for this section. The app reads stored data only -- it does not call "
    "FRED itself. Run the data pipeline with FRED_API_KEY set (see the README), then restart the app."
)

UP_COLOR = "#55efc4"
DOWN_COLOR = "#d63031"

# Financial Times house style for the charts.
FT_PAPER = "#FFF1E5"
FT_TEXT = "#33302E"
FT_MUTED = "#66605C"
FT_GRID = "#E6D9CE"
FT_BLUE = "#0F5499"
FT_CLARET = "#990F3D"
FT_TEAL = "#0D7680"
FT_OXFORD = "#262A33"
FT_MANDARIN = "#FF8833"
FT_FONT = "Metric, 'Helvetica Neue', Helvetica, Arial, sans-serif"
FT_BASE_FONT_SIZE = 14  # Plotly's default is 12
FT_SOURCE = "Source: FRED, Federal Reserve Bank of St. Louis"


def _today() -> date:
    """Indirection so tests can pin the date (FOMC years shown depend on it)."""
    return date.today()


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


def _card(title: str, content_id: str, header_extra=None, margin: bool = True) -> dbc.Row:
    header = [html.Span(title, style={"marginRight": "15px"})]
    if header_extra is not None:
        header.append(header_extra)
    return dbc.Row(
        dbc.Col(
            dbc.Card([
                dbc.CardHeader(header, style={"color": colors["text"], "backgroundColor": colors["background"]}),
                dbc.CardBody(html.Div(id=content_id), style={"backgroundColor": colors["background"]}),
            ], style={"backgroundColor": colors["background"], **({"marginBottom": "20px"} if margin else {})}),
            width=12,
        )
    )


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
                    "A snapshot, not a forecast. Macro moves, FRED data and the news digest below reflect a small "
                    "tracked universe and a handful of benchmark series, not comprehensive market coverage. "
                    "Green/red indicates direction (up/down) only -- not a judgement about whether that "
                    "direction is good or bad news, which depends on context this page doesn't attempt to judge.",
                    color="warning", style={"marginBottom": "20px"},
                ), width=12,
            )
        ),

        _card("Macro Moves", "marketcond-moves-table"),
        _card("Rates & Curve (FRED)", "marketcond-rates-content"),
        _card("Rate Expectations (FRED)", "marketcond-expectations-content"),
        _card("Labor Market (FRED)", "marketcond-labor-content"),
        _card("Inflation (FRED)", "marketcond-inflation-content"),
        _card("Market News", "marketcond-news-content",
              header_extra=dbc.Button("Refresh Headlines", id="marketcond-news-button", size="sm", color="secondary"),
              margin=False),
    ], fluid=True, style={"backgroundColor": colors["background"]})


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def _note(text: str) -> html.P:
    return html.P(text, style={"color": colors["text"], "fontSize": "0.85rem", "opacity": 0.85, "marginTop": "10px"})


def _dark_table(columns: list[dict], rows: list[dict], style_data_conditional=None, filterable: bool = False,
                min_width: str = "100px") -> dash_table.DataTable:
    kwargs = {"filter_action": "native"} if filterable else {}
    return dash_table.DataTable(
        columns=columns, data=rows, sort_action="native", **kwargs,
        style_header={"backgroundColor": colors["background"], "color": colors["text"], "fontWeight": "bold"},
        style_data={"backgroundColor": colors["background"], "color": colors["text"]},
        style_cell={"minWidth": min_width, "textAlign": "left"},
        style_data_conditional=style_data_conditional or [],
    )


def _fmt_date(value) -> str:
    return "n/a" if value is None or pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def _obs(by_series: dict[str, pd.DataFrame], series_id: str) -> pd.DataFrame | None:
    """Sorted, NaN-free observations for one series, or None if there are none."""
    df = by_series.get(series_id)
    if df is None or df.empty:
        return None
    df = df.dropna(subset=["value"]).sort_values("date")
    return None if df.empty else df.assign(date=pd.to_datetime(df["date"]))


def _ft_figure(title: str, subtitle: str, y_suffix: str = "") -> go.Figure:
    """Empty figure in FT house style: pale paper, left-aligned title with a
    muted subtitle, horizontal gridlines only, no zero line, legend on top,
    text a size up from Plotly's default, and a source line."""
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=f"{title}<br><sup>{subtitle}</sup>", x=0, xanchor="left",
                   font=dict(size=FT_BASE_FONT_SIZE + 6, color=FT_TEXT)),
        paper_bgcolor=FT_PAPER, plot_bgcolor=FT_PAPER,
        font=dict(family=FT_FONT, size=FT_BASE_FONT_SIZE, color=FT_TEXT),
        xaxis=dict(showgrid=False, linecolor=FT_TEXT, ticks="outside", tickcolor=FT_TEXT),
        yaxis=dict(showgrid=True, gridcolor=FT_GRID, zeroline=False, ticksuffix=y_suffix, side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
        margin=dict(l=20, r=20, t=100, b=70),
        annotations=[dict(text=FT_SOURCE, xref="paper", yref="paper", x=0, y=-0.16, xanchor="left",
                          showarrow=False, font=dict(size=FT_BASE_FONT_SIZE - 2, color=FT_MUTED))],
    )
    return fig


def _graph(fig: go.Figure) -> dcc.Graph:
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"marginTop": "10px"})


def _release_table(rows: list[dict]) -> dash_table.DataTable:
    show_yoy = any(spec_for(r["series_id"]).show_yoy for r in rows)
    ids = RELEASE_COLUMNS + (["yoy"] if show_yoy else [])
    data = [{
        "name": r["name"],
        "latest_date": _fmt_date(r["latest_date"]),
        "latest": format_level(spec_for(r["series_id"]), r["latest_value"]),
        "prior": format_level(spec_for(r["series_id"]), r["prior_value"]),
        "change": format_change(spec_for(r["series_id"]), r["change"]),
        "yoy": format_yoy(r["yoy"]) if spec_for(r["series_id"]).show_yoy else "",
        "_change_raw": r["change"] or 0,
    } for r in rows]
    return _dark_table([{"name": RELEASE_COLUMN_LABELS[c], "id": c} for c in ids], data,
                       style_data_conditional=_change_style("_change_raw", "change"))


# ---------------------------------------------------------------------------
# Section renderers (pure functions of the by-series dict)
# ---------------------------------------------------------------------------

def _render_rates(by_series: dict[str, pd.DataFrame]):
    rows = build_release_summary(by_series, category="rates")
    if not rows:
        return html.P(NO_FRED_MESSAGE, style={"color": colors["text"]})

    children = [_release_table(rows)]

    yields = [(sid, label, color) for sid, label, color in
              [("DGS10", "10Y", FT_BLUE), ("DGS2", "2Y", FT_CLARET), ("DGS3MO", "3M", FT_TEAL)]
              if _obs(by_series, sid) is not None]
    if yields:
        fig = _ft_figure("Treasury yields", "Percent, daily", y_suffix="%")
        for sid, label, color in yields:
            df = _obs(by_series, sid)
            fig.add_trace(go.Scatter(x=df["date"], y=df["value"], name=f"{label} Treasury",
                                     line=dict(color=color, width=2.5)))
        children.append(_graph(fig))

    spread = _obs(by_series, "T10Y2Y")
    if spread is not None:
        bp = spread["value"] * 100  # FRED publishes the spread in percentage points
        fig = _ft_figure("10Y-2Y spread (2s10s)", "Basis points, daily; shaded where the curve is inverted",
                         y_suffix=" bp")
        fig.add_trace(go.Scatter(x=spread["date"], y=bp, name="10Y-2Y spread", line=dict(color=FT_OXFORD, width=2.5)))
        fig.add_trace(go.Scatter(x=spread["date"], y=bp.clip(upper=0), name="Inverted", fill="tozeroy",
                                 line=dict(width=0), fillcolor="rgba(153,15,61,0.35)", hoverinfo="skip"))
        children.append(_graph(fig))
    return children


def _render_expectations(by_series: dict[str, pd.DataFrame]):
    policy = current_policy_rate(by_series)
    policy_rate = policy[0] if policy else None
    sep_rows = build_sep_table(by_series.get("FEDTARMD"), by_series.get("FEDTARMDLR"), policy_rate, _today())
    proxy_rows = build_market_proxies(by_series)
    if not sep_rows and not proxy_rows:
        return html.P(NO_FRED_MESSAGE, style={"color": colors["text"]})

    children = []
    if sep_rows:
        data = [{
            "label": r["label"], "median": f"{r['median']:.2f}%",
            "vs_current": "n/a" if r["vs_current_bp"] is None else f"{r['vs_current_bp']:+.0f} bp",
            "_gap_raw": r["vs_current_bp"] or 0,
        } for r in sep_rows]
        children.append(html.H6("FOMC projections (Summary of Economic Projections)",
                                style={"color": colors["text"]}))
        children.append(_dark_table(SEP_COLUMNS, data, style_data_conditional=_change_style("_gap_raw", "vs_current")))
        current = (f"Current rate used for comparison: {policy_rate:.2f}% ({policy[1]}). " if policy else
                   "No current policy rate available, so no comparison is shown. ")
        children.append(_note(
            current + "The FOMC median is the Fed's own projection of where it expects to set rates, not market "
            "pricing. FRED holds only the latest vintage, so this shows where the median sits now, not how it "
            "moved since the previous projections."))

    if proxy_rows:
        data = [{
            "name": r["name"], "yield_": f"{r['yield_']:.2f}%", "policy_rate": f"{r['policy_rate']:.2f}%",
            "gap": f"{r['gap_bp']:+.0f} bp", "reading": r["reading"], "as_of": _fmt_date(r["as_of"]),
            "_gap_raw": r["gap_bp"],
        } for r in proxy_rows]
        children.append(html.H6("What the market is leaning toward (proxies)",
                                style={"color": colors["text"], "marginTop": "20px"}))
        children.append(_dark_table(PROXY_COLUMNS, data, style_data_conditional=_change_style("_gap_raw", "gap")))
        children.append(_note(
            f"These are proxies, not probabilities: a short-dated Treasury yield below the effective fed funds "
            f"rate is consistent with the market pricing cuts, above with pricing hikes (gaps within "
            f"{NOISE_BAND_BP} bp read as roughly in line). Term premium and bill supply move them too. "
            "Fed funds futures, the usual source of market-implied probabilities, are not in FRED."))

    lines = [(sid, label, color) for sid, label, color in
             [("DFF", "Effective fed funds rate", FT_OXFORD), ("DGS3MO", "3M Treasury bill", FT_TEAL),
              ("DGS2", "2Y Treasury", FT_CLARET)] if _obs(by_series, sid) is not None]
    projected = [r for r in sep_rows if r["year"] is not None]
    if lines or projected:
        fig = _ft_figure("Policy rate, front-end yields and FOMC projections",
                         "Percent; markers are the FOMC median at each year-end", y_suffix="%")
        for sid, label, color in lines:
            df = _obs(by_series, sid)
            fig.add_trace(go.Scatter(x=df["date"], y=df["value"], name=label, line=dict(color=color, width=2.5)))
        if projected:
            fig.add_trace(go.Scatter(
                x=[date(r["year"], 12, 31) for r in projected], y=[r["median"] for r in projected],
                name="FOMC median projection", mode="markers",
                marker=dict(color=FT_MANDARIN, size=11, symbol="diamond", line=dict(color=FT_TEXT, width=1)),
            ))
        children.append(_graph(fig))
    return children


def _render_release_category(by_series: dict[str, pd.DataFrame], category: str, note: str | None = None):
    rows = build_release_summary(by_series, category=category)
    if not rows:
        return html.P(NO_FRED_MESSAGE, style={"color": colors["text"]})
    children = [_release_table(rows)]
    if note:
        children.append(_note(note))
    return children


def _observations_by_series(release_data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if release_data is None or release_data.empty:
        return {}
    return {
        series_id: group.sort_values("date")[["date", "value"]].reset_index(drop=True)
        for series_id, group in release_data.groupby("series_id")
    }


def register_market_conditions_callback(
    app: dash.Dash,
    economic_data: pd.DataFrame,
    economic_release_data: pd.DataFrame,
) -> None:
    yfinance_client = YFinanceClient()
    by_series = _observations_by_series(economic_release_data)

    @app.callback(Output("marketcond-moves-table", "children"), [Input("marketcond-moves-table", "id")])
    def render_moves_table(_):
        moves = compute_asset_moves(economic_data)
        if not moves:
            return html.P("No asset-class data available.", style={"color": colors["text"]})

        rows = [_format_moves_row(m) for m in moves]
        rows.sort(key=lambda r: (r["asset_class"], r["ticker"]))
        return _dark_table(
            [{"name": MOVES_COLUMN_LABELS[c], "id": c} for c in MOVES_COLUMNS], rows, filterable=True,
            min_width="90px",
            style_data_conditional=(
                _change_style("_1d_raw", "change_1d") + _change_style("_1w_raw", "change_1w")
                + _change_style("_1m_raw", "change_1m")
            ),
        )

    @app.callback(Output("marketcond-rates-content", "children"), [Input("marketcond-rates-content", "id")])
    def render_rates(_):
        return _render_rates(by_series)

    @app.callback(Output("marketcond-expectations-content", "children"),
                  [Input("marketcond-expectations-content", "id")])
    def render_expectations(_):
        return _render_expectations(by_series)

    @app.callback(Output("marketcond-labor-content", "children"), [Input("marketcond-labor-content", "id")])
    def render_labor(_):
        return _render_release_category(
            by_series, "labor",
            "Payrolls and JOLTS in thousands of persons (change = jobs added / openings change); unemployment "
            "change in percentage points; claims weekly; wages show year-on-year growth.")

    @app.callback(Output("marketcond-inflation-content", "children"), [Input("marketcond-inflation-content", "id")])
    def render_inflation(_):
        return _render_release_category(
            by_series, "inflation",
            "Price indices: Change is month-on-month, YoY is against the same month a year earlier. "
            "Core excludes food and energy.")

    @app.callback(Output("marketcond-news-content", "children"), [Input("marketcond-news-button", "n_clicks")])
    def render_news(n_clicks):
        if not n_clicks:
            return html.P("Click \"Refresh Headlines\" to pull the latest market news.", style={"color": colors["text"]})

        news_by_source = {}
        status = []  # per-ticker outcome, so an empty result says why
        for ticker in NEWS_BASKET_TICKERS:
            try:
                items = yfinance_client.fetch_news(ticker) or []
                news_by_source[ticker] = items
                status.append(f"{ticker}: {len(items)} items")
            except Exception as exc:  # network, rate limit, yfinance format change: don't hide it
                logger.warning("Headline fetch failed for %s: %s: %s", ticker, type(exc).__name__, exc)
                news_by_source[ticker] = []
                status.append(f"{ticker}: failed ({type(exc).__name__})")

        headlines = dedupe_headlines(news_by_source)
        if not headlines:
            return html.Div([
                html.P("No headlines available right now.", style={"color": colors["text"]}),
                html.P("Fetch status -- " + "; ".join(status) + ". Details are in the app log.",
                       style={"color": colors["text"], "fontSize": "0.85em"}),
            ])

        return html.Ul([_render_headline(h) for h in headlines])


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


def _render_headline(headline: dict) -> html.Li:
    also_from = f" (also: {', '.join(headline['also_from'])})" if headline["also_from"] else ""
    label = f"{headline['title']} — {headline['source']}{also_from}"
    if headline.get("link"):
        content = html.A(label, href=headline["link"], target="_blank", style={"color": colors["text"]})
    else:
        content = label
    return html.Li(content, style={"color": colors["text"], "marginBottom": "6px"})
