"""Page-level tests for Market Conditions: callbacks are exercised through a
real `dash.Dash` app, with the moves table fed by the real
DB -> `Repository.fetch_dataframe` path (the path that broke)."""
from __future__ import annotations

from datetime import date, timedelta

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import pytest

from src.peer_comparison_tool.comparison_tool import market_conditions_page as page
from src.peer_comparison_tool.data.clients.yfinance_client import DataRetrievalError
from peer_comparison_tool.data.models import AssetClassTimeSeries
from peer_comparison_tool.data.repository import Repository


class FakeNewsClient:
    def __init__(self, by_ticker: dict):
        self._by_ticker = by_ticker

    def fetch_news(self, ticker: str):
        result = self._by_ticker.get(ticker, [])
        if isinstance(result, Exception):
            raise result
        return result


def _build_app(monkeypatch, economic_data, release_data=None, news=None):
    monkeypatch.setattr(page, "YFinanceClient", lambda: FakeNewsClient(news or {}))
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY], suppress_callback_exceptions=True)
    app.layout = page.get_market_conditions_page_layout()
    page.register_market_conditions_callback(
        app, economic_data, release_data if release_data is not None else pd.DataFrame())
    return app


def _callback(app, fragment: str):
    for key, cb in app.callback_map.items():
        if fragment in key:
            return cb["callback"].__wrapped__
    raise AssertionError(f"no callback for {fragment}")


def _economic_data_from_db(session) -> pd.DataFrame:
    repo = Repository(session)
    rows = []
    for ticker, asset_class, base in [("Gold", "commodity", 2000.0), ("US10Y_Yield", "rate", 4.0)]:
        for i in range(30):
            rows.append({"ticker": ticker, "date": date(2026, 1, 1) + timedelta(days=i),
                         "asset_class": asset_class, "close_price": base + i * 0.1})
    repo.upsert_dataframe(AssetClassTimeSeries, pd.DataFrame(rows))
    session.commit()
    return repo.fetch_dataframe(AssetClassTimeSeries)


def _flatten_text(component) -> str:
    """All text in a Dash component tree (children / table data)."""
    if component is None:
        return ""
    if isinstance(component, str):
        return component
    if isinstance(component, (list, tuple)):
        return " ".join(_flatten_text(c) for c in component)
    data = getattr(component, "data", None)
    parts = [" ".join(str(v) for r in data for v in r.values()) if data else ""]
    parts.append(_flatten_text(getattr(component, "children", None)))
    return " ".join(parts)


def test_moves_table_renders_from_real_db_frame(monkeypatch, session):
    """Regression: KeyError 'asset_class' when economic_data came straight
    from `fetch_dataframe` (DB column name "AssetClass")."""
    app = _build_app(monkeypatch, _economic_data_from_db(session))
    table = _callback(app, "marketcond-moves-table.children")(None)
    tickers = {r["ticker"]: r for r in table.data}
    assert set(tickers) == {"Gold", "US10Y_Yield"}
    assert tickers["Gold"]["asset_class"] == "commodity"
    assert tickers["Gold"]["change_1d"].endswith("%")


def test_moves_table_empty_state(monkeypatch):
    app = _build_app(monkeypatch, pd.DataFrame())
    out = _callback(app, "marketcond-moves-table.children")(None)
    assert "No asset-class data" in _flatten_text(out)


def test_moves_table_with_null_asset_class_does_not_crash_the_sort(monkeypatch, session):
    df = _economic_data_from_db(session)
    df.loc[df["ticker"] == "Gold", "asset_class"] = None  # pre-backfill rows
    app = _build_app(monkeypatch, df)
    table = _callback(app, "marketcond-moves-table.children")(None)
    assert {r["ticker"] for r in table.data} == {"Gold", "US10Y_Yield"}


def test_news_prompts_before_first_click(monkeypatch):
    app = _build_app(monkeypatch, pd.DataFrame())
    assert "Refresh Headlines" in _flatten_text(_callback(app, "marketcond-news-content.children")(None))


def test_news_renders_both_yfinance_item_shapes_and_survives_one_failing_ticker(monkeypatch):
    news = {
        "SPY": [{"title": "Stocks rally on rate hopes", "publisher": "Wire", "link": "https://x.test/a"}],
        "^VIX": DataRetrievalError("boom"),
        "^TNX": [{"content": {"title": "Yields slip after jobs data",
                              "provider": {"displayName": "Reuters"},
                              "canonicalUrl": {"url": "https://x.test/b"}}}],
    }
    app = _build_app(monkeypatch, pd.DataFrame(), news=news)
    text = _flatten_text(_callback(app, "marketcond-news-content.children")(1))
    assert "Stocks rally on rate hopes" in text
    assert "Yields slip after jobs data" in text


def test_news_all_sources_failing_shows_empty_message(monkeypatch):
    news = {t: DataRetrievalError("down") for t in page.NEWS_BASKET_TICKERS}
    app = _build_app(monkeypatch, pd.DataFrame(), news=news)
    assert "No headlines" in _flatten_text(_callback(app, "marketcond-news-content.children")(1))


# ===========================================================================
# FRED-backed sections: Rates & Curve, Rate Expectations, Labor, Inflation
# ===========================================================================
from datetime import date as _date  # noqa: E402

TODAY = _date(2026, 10, 11)


def _walk(component):
    """Every Dash component in a (possibly nested / list) children tree."""
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


def _fred_frame() -> pd.DataFrame:
    rows: list[tuple[str, _date, float]] = []

    def daily(sid, values, start=_date(2026, 9, 1)):
        rows.extend((sid, start + timedelta(days=i), v) for i, v in enumerate(values))

    def monthly(sid, values, year=2025, month=1):
        for v in values:
            rows.append((sid, _date(year, month, 1), v))
            month += 1
            if month == 13:
                year, month = year + 1, 1

    daily("DGS10", [4.00 + 0.01 * i for i in range(30)])
    daily("T10Y2Y", [0.10 - 0.01 * i for i in range(30)])    # ends inverted: -0.19
    daily("DFF", [4.33] * 30)
    daily("DFEDTARU", [4.50] * 30)
    daily("DFEDTARL", [4.25] * 30)
    daily("DGS3MO", [4.00] * 30)                              # 33 bp below fed funds
    daily("DGS2", [4.50] * 30)                                # 17 bp above fed funds
    rows += [("FEDTARMD", _date(2025, 1, 1), 4.125), ("FEDTARMD", _date(2026, 1, 1), 3.875),
             ("FEDTARMD", _date(2027, 1, 1), 3.625), ("FEDTARMD", _date(2028, 1, 1), 3.375),
             ("FEDTARMDLR", _date(2028, 1, 1), 3.0)]
    monthly("PAYEMS", [159_000 + 100 * i for i in range(14)])
    monthly("UNRATE", [4.0 + 0.1 * i for i in range(14)])
    monthly("JTSJOL", [7_200 - 20 * i for i in range(14)])
    rows.extend(("ICSA", _date(2026, 9, 5) + timedelta(days=7 * i), 230_000 + 1_000 * i) for i in range(6))
    monthly("CES0500000003", [35.0 + 0.1 * i for i in range(14)])
    monthly("CPIAUCSL", [300.0 + i for i in range(14)])
    monthly("CPILFESL", [310.0 + i for i in range(14)])
    monthly("PCEPILFE", [120.0 + 0.3 * i for i in range(14)])
    return pd.DataFrame(rows, columns=["series_id", "date", "value"])


def _fred_app(monkeypatch, frame=None):
    monkeypatch.setattr(page, "_today", lambda: TODAY)
    return _build_app(monkeypatch, pd.DataFrame(), release_data=_fred_frame() if frame is None else frame)


def _row(table, name):
    return next(r for r in table.data if r["name"] == name)


def test_layout_has_every_section_in_order():
    ids = [c.id for c in _walk(page.get_market_conditions_page_layout()) if getattr(c, "id", None)]
    order = ["marketcond-moves-table", "marketcond-rates-content", "marketcond-expectations-content",
             "marketcond-labor-content", "marketcond-inflation-content", "marketcond-news-content"]
    assert [i for i in ids if i in order] == order


def test_rates_section_table_uses_basis_points_and_percent_levels(monkeypatch):
    out = _callback(_fred_app(monkeypatch), "marketcond-rates-content.children")(None)
    [table] = _tables(out)
    ten = _row(table, "10Y Treasury Yield")
    assert ten["latest"] == "4.29%" and ten["prior"] == "4.28%" and ten["change"] == "+1 bp"
    spread = _row(table, "10Y-2Y Spread (2s10s)")
    assert spread["latest"] == "-19 bp" and spread["change"] == "-1 bp"
    names = [r["name"] for r in table.data]  # catalog order, not alphabetical
    assert names.index("10Y Treasury Yield") < names.index("2Y Treasury Yield") < names.index("10Y-2Y Spread (2s10s)")
    assert "yoy" not in [c["id"] for c in table.columns]


def test_rates_charts_are_ft_styled_and_spread_is_in_bp(monkeypatch):
    out = _callback(_fred_app(monkeypatch), "marketcond-rates-content.children")(None)
    figs = {g.figure.layout.title.text.split("<br>")[0]: g.figure for g in _graphs(out)}
    assert any("Treasury yields" in k for k in figs) and any("2s10s" in k for k in figs)

    for fig in figs.values():
        assert fig.layout.paper_bgcolor == page.FT_PAPER
        assert fig.layout.font.size >= 14           # a size up from Plotly's default 12
        assert fig.layout.title.x == 0               # FT: left-aligned title
        assert fig.layout.xaxis.showgrid is False    # FT: horizontal gridlines only

    spread_fig = next(f for k, f in figs.items() if "2s10s" in k)
    main_line = next(t for t in spread_fig.data if t.name == "10Y-2Y spread")
    assert main_line.y[-1] == pytest.approx(-19.0)   # percentage points -> basis points
    inverted = next(t for t in spread_fig.data if t.name == "Inverted")
    assert max(inverted.y) <= 0                      # shading only below zero


def test_expectations_sep_table_and_gap_to_current(monkeypatch):
    out = _callback(_fred_app(monkeypatch), "marketcond-expectations-content.children")(None)
    sep, _proxies = _tables(out)
    assert [r["label"] for r in sep.data] == ["2026 year-end", "2027 year-end", "2028 year-end", "Longer run"]
    by_label = {r["label"]: r for r in sep.data}
    # current = midpoint of 4.25-4.50 = 4.375
    assert by_label["2026 year-end"]["vs_current"] == "-50 bp"
    assert by_label["2027 year-end"]["vs_current"] == "-75 bp"
    text = _flatten_text(out)
    assert "target-range midpoint" in text and "4.38%" in text   # states what "current" means


def test_expectations_proxies_are_labelled_as_proxies_not_probabilities(monkeypatch):
    out = _callback(_fred_app(monkeypatch), "marketcond-expectations-content.children")(None)
    _sep, proxies = _tables(out)
    by_name = {r["name"]: r for r in proxies.data}
    assert by_name["3M Treasury bill vs fed funds"]["gap"] == "-33 bp"
    assert by_name["3M Treasury bill vs fed funds"]["reading"] == "cuts priced in"
    assert by_name["2Y Treasury vs fed funds"]["reading"] == "hikes priced in"
    text = _flatten_text(out).lower()
    assert "proxies" in text and "probabilit" in text
    assert "not market pricing" in text and "fed's own" in text   # SEP caveat: the Fed's view, not the market's


def test_expectations_chart_overlays_fomc_medians_at_year_end(monkeypatch):
    out = _callback(_fred_app(monkeypatch), "marketcond-expectations-content.children")(None)
    [graph] = _graphs(out)
    markers = next(t for t in graph.figure.data if "FOMC" in (t.name or ""))
    assert [pd.Timestamp(x) for x in markers.x] == [pd.Timestamp(2026, 12, 31), pd.Timestamp(2027, 12, 31),
                                                    pd.Timestamp(2028, 12, 31)]
    assert list(markers.y) == [3.875, 3.625, 3.375]   # 2025 is realized, not a projection: excluded
    assert {"Effective fed funds rate", "3M Treasury bill", "2Y Treasury"} <= {t.name for t in graph.figure.data}


def test_labor_section_units_and_yoy_column(monkeypatch):
    out = _callback(_fred_app(monkeypatch), "marketcond-labor-content.children")(None)
    [table] = _tables(out)
    assert _row(table, "Nonfarm Payrolls")["change"] == "+100k"       # jobs added, not a % of the level
    assert _row(table, "Unemployment Rate")["change"] == "+0.1 pp"    # not "+2.4%"
    assert _row(table, "Initial Jobless Claims")["change"] == "+1k"
    wages = _row(table, "Avg Hourly Earnings (Private)")
    assert wages["latest"].startswith("$") and wages["yoy"].endswith("%")
    assert "yoy" in [c["id"] for c in table.columns]


def test_inflation_section_shows_mom_and_yoy(monkeypatch):
    out = _callback(_fred_app(monkeypatch), "marketcond-inflation-content.children")(None)
    [table] = _tables(out)
    cpi = _row(table, "CPI (All Items)")
    # latest is Feb-26 = 313.0 vs 312.0 prior month; exact year-ago Feb-25 = 301.0 -> 313/301 - 1 = +3.99%
    assert cpi["change"] == "+0.3%" and cpi["yoy"] == "+4.0%"
    assert {r["name"] for r in table.data} == {"CPI (All Items)", "Core CPI (ex Food & Energy)", "Core PCE Price Index"}


@pytest.mark.parametrize("fragment", ["rates", "expectations", "labor", "inflation"])
def test_every_fred_section_has_a_helpful_empty_state(monkeypatch, fragment):
    app = _fred_app(monkeypatch, frame=pd.DataFrame(columns=["series_id", "date", "value"]))
    out = _callback(app, f"marketcond-{fragment}-content.children")(None)
    assert "FRED_API_KEY" in _flatten_text(out)
    assert not _tables(out) and not _graphs(out)


def test_partial_data_renders_what_exists_without_crashing(monkeypatch):
    frame = _fred_frame()
    app = _fred_app(monkeypatch, frame=frame[frame["series_id"] == "DGS10"])

    rates = _callback(app, "marketcond-rates-content.children")(None)
    [table] = _tables(rates)
    assert [r["name"] for r in table.data] == ["10Y Treasury Yield"]
    assert len(_graphs(rates)) == 1                        # yields chart only; no spread data -> no spread chart

    expectations = _callback(app, "marketcond-expectations-content.children")(None)
    assert not _tables(expectations) and "FRED_API_KEY" in _flatten_text(expectations)


def test_sep_table_without_a_policy_rate_still_renders(monkeypatch):
    frame = _fred_frame()
    frame = frame[frame["series_id"].isin(["FEDTARMD", "FEDTARMDLR"])]
    out = _callback(_fred_app(monkeypatch, frame), "marketcond-expectations-content.children")(None)
    [sep] = _tables(out)
    assert all(r["vs_current"] == "n/a" for r in sep.data)
    assert "No current policy rate" in _flatten_text(out)
