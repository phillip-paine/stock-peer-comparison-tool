"""Tests for the sector / sub-industry filter on the valuation dispersion page.

Helpers are tested directly; the callbacks are exercised through a real
`dash.Dash` app so the component IDs / Input-State wiring are verified too,
not just the helper logic.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import dash
import dash_bootstrap_components as dbc

from src.peer_comparison_tool.comparison_tool import valuation_dispersion_page as page


def _snapshot() -> pd.DataFrame:
    """Two sectors, three sub-industries; Tech/Apps has 5 tickers so it
    clears the default min_group_size=4 and gets scored."""
    rows = []
    for i, pe in enumerate([10, 12, 14, 16, 40]):
        rows.append(("Tech", "Apps", f"APP{i}", pe))
    for i, pe in enumerate([8, 9, 10, 11, 30]):
        rows.append(("Tech", "Chips", f"CHP{i}", pe))
    for i, pe in enumerate([20, 22, 24, 26, 60]):
        rows.append(("Health", "Pharma", f"PHM{i}", pe))
    df = pd.DataFrame(rows, columns=["sector", "sub_industry", "ticker", "price_eps_ratio"])
    df["name"] = df["ticker"] + " Corp"
    df["label"] = 0
    df["market_cap_MM"] = 1000.0
    df["enterpriseToEbitda"] = df["price_eps_ratio"] * 0.8
    df["price_to_book"] = df["price_eps_ratio"] * 0.1
    # Quality must vary within a group or its z-score is undefined (std 0)
    # and nothing gets a signal. The priciest name in each group (index 4)
    # gets the best quality -> "expensive, quality strong".
    idx = df.groupby("sub_industry").cumcount()
    df["return_on_equity"] = 0.05 + 0.02 * idx
    df["profit_margin"] = 0.05 + 0.02 * idx
    df["debt_to_equity_ratio"] = 2.0 - 0.1 * idx
    return df


def test_sector_options_sorted_deduped_and_nan_free():
    df = _snapshot()
    df.loc[0, "sector"] = np.nan
    df.loc[1, "sector"] = ""
    opts = page._sector_options(df)
    assert [o["value"] for o in opts] == ["Health", "Tech"]
    assert all(o["label"] == o["value"] for o in opts)


def test_sub_industry_options_cascade_and_default_to_all():
    df = _snapshot()
    assert [o["value"] for o in page._sub_industry_options(df, None)] == ["Apps", "Chips", "Pharma"]
    assert [o["value"] for o in page._sub_industry_options(df, [])] == ["Apps", "Chips", "Pharma"]
    assert [o["value"] for o in page._sub_industry_options(df, ["Tech"])] == ["Apps", "Chips"]
    assert [o["value"] for o in page._sub_industry_options(df, ["Health"])] == ["Pharma"]


def test_options_helpers_tolerate_missing_columns():
    df = pd.DataFrame({"ticker": ["A"]})
    assert page._sector_options(df) == []
    assert page._sub_industry_options(df, ["Tech"]) == []


def test_filter_by_selection_semantics():
    df = _snapshot()
    assert len(page._filter_by_selection(df, None, None)) == 15
    assert len(page._filter_by_selection(df, [], [])) == 15
    assert set(page._filter_by_selection(df, ["Tech"], None)["sub_industry"]) == {"Apps", "Chips"}
    assert set(page._filter_by_selection(df, ["Tech"], ["Apps"])["sub_industry"]) == {"Apps"}
    assert set(page._filter_by_selection(df, None, ["Pharma"])["sector"]) == {"Health"}
    assert page._filter_by_selection(df, ["Health"], ["Apps"]).empty  # incompatible -> empty, not a crash


def test_filter_by_selection_returns_copy():
    df = _snapshot()
    out = page._filter_by_selection(df, ["Tech"], None)
    out["price_eps_ratio"] = -1
    assert (df["price_eps_ratio"] != -1).all()


def _build_app(snapshot: pd.DataFrame):
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY], suppress_callback_exceptions=True)
    app.layout = page.get_valuation_dispersion_page_layout(snapshot)
    page.register_valuation_dispersion_callback(app, snapshot)
    return app


def _callback(app, output_fragment: str):
    for key, cb in app.callback_map.items():
        if output_fragment in key:
            return cb["callback"].__wrapped__
    raise AssertionError(f"callback for {output_fragment} not registered")


def test_layout_has_multi_searchable_dropdowns():
    app = _build_app(_snapshot())
    found = {}

    def walk(node):
        if getattr(node, "id", None) in ("valdisp-sector-dropdown", "valdisp-sub-sector-dropdown"):
            found[node.id] = node
        children = getattr(node, "children", None)
        if isinstance(children, (list, tuple)):
            for c in children:
                walk(c)
        elif children is not None and not isinstance(children, str):
            walk(children)

    walk(app.layout)
    assert set(found) == {"valdisp-sector-dropdown", "valdisp-sub-sector-dropdown"}
    for dd in found.values():
        assert dd.multi is True and dd.searchable is True
    assert [o["value"] for o in found["valdisp-sector-dropdown"].options] == ["Health", "Tech"]


def test_sub_sector_callback_prunes_stale_selection():
    app = _build_app(_snapshot())
    cb = _callback(app, "valdisp-sub-sector-dropdown.options")
    options, value = cb(["Tech"], ["Apps", "Pharma"])  # Pharma belongs to Health
    assert [o["value"] for o in options] == ["Apps", "Chips"]
    assert value == ["Apps"]
    options, value = cb([], None)
    assert len(options) == 3 and value == []


def _run(cb, sectors, subs):
    return cb(1, "sub_industry", 4, -1.0, 1.0, sectors, subs)


def test_run_screen_filters_output_but_not_peer_statistics():
    snap = _snapshot()
    app = _build_app(snap)
    cb = _callback(app, "valdisp-summary-table.data")

    rows_all, _, fig_all = _run(cb, [], [])
    rows_tech, status, fig_tech = _run(cb, ["Tech"], [])
    rows_apps, _, fig_apps = _run(cb, ["Tech"], ["Apps"])

    tickers = lambda rows: {r["ticker"] for r in rows}
    assert tickers(rows_tech) <= tickers(rows_all)
    assert all(t.startswith(("APP", "CHP")) for t in tickers(rows_tech))
    assert all(t.startswith("APP") for t in tickers(rows_apps))
    assert "showing 10" in status
    assert tickers(rows_all) == {"APP4", "CHP4", "PHM4"}  # sanity: fixture really produces flags
    assert tickers(rows_tech) == {"APP4", "CHP4"}
    assert tickers(rows_apps) == {"APP4"}

    # Z-scores for a ticker are identical filtered vs unfiltered (filter is post-scoring).
    z_all = {r["ticker"]: r["valuation_zscore"] for r in rows_all}
    for r in rows_tech:
        assert r["valuation_zscore"] == z_all[r["ticker"]]

    plotted = {t for tr in fig_apps.data for t in (tr.text if tr.text is not None else [])}
    assert plotted and all(t.startswith("APP") for t in plotted)


def test_run_screen_empty_selection_result_does_not_crash():
    app = _build_app(_snapshot())
    cb = _callback(app, "valdisp-summary-table.data")
    rows, status, _ = _run(cb, ["Health"], ["Apps"])
    assert rows == []
    assert "No tickers match" in status


def test_run_screen_does_not_mutate_shared_snapshot():
    snap = _snapshot()
    before = snap.copy()
    app = _build_app(snap)
    cb = _callback(app, "valdisp-summary-table.data")
    _run(cb, ["Tech"], ["Apps"])
    pd.testing.assert_frame_equal(snap, before)
