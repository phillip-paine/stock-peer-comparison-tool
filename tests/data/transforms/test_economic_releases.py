"""FRED series catalog and the pure transforms behind the Market Conditions
economic sections."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from peer_comparison_tool.data.transforms import economic_releases as er
from peer_comparison_tool.data.transforms.economic_releases import (
    FRED_SERIES, SERIES_CATALOG, build_market_proxies, build_release_summary, build_sep_table,
    current_policy_rate, format_change, format_level, format_yoy, latest_vs_prior_release,
)


def obs(pairs) -> pd.DataFrame:
    return pd.DataFrame({"date": [d for d, _ in pairs], "value": [v for _, v in pairs]})


def monthly(start_year, start_month, values) -> pd.DataFrame:
    rows, y, m = [], start_year, start_month
    for v in values:
        rows.append((date(y, m, 1), v))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return obs(rows)


def _daily(start_day, values):
    return obs([(date(2026, 10, start_day + i), v) for i, v in enumerate(values)])


# ---- catalog ------------------------------------------------------------------
def test_catalog_entries_are_internally_consistent():
    for key, spec in SERIES_CATALOG.items():
        assert spec.series_id == key and spec.name
        assert spec.category in er.CATEGORY_LABELS
        assert spec.frequency in er.HISTORY_LIMIT_BY_FREQUENCY
        assert spec.level_kind in er.LEVEL_KINDS
        assert spec.change_mode in er.CHANGE_MODES


def test_catalog_covers_the_agreed_scope():
    required = {"DGS10", "DGS2", "DGS3MO", "T10Y2Y", "DFF", "DFEDTARU", "DFEDTARL", "FEDTARMD", "FEDTARMDLR",
                "PAYEMS", "UNRATE", "JTSJOL", "ICSA", "CES0500000003", "CPIAUCSL", "CPILFESL", "PCEPILFE"}
    assert required <= set(SERIES_CATALOG)


def test_history_limit_leaves_room_for_yoy_and_is_longer_for_daily_series():
    for spec in SERIES_CATALOG.values():
        if spec.show_yoy:
            assert spec.history_limit >= 14
    assert SERIES_CATALOG["DGS10"].history_limit > SERIES_CATALOG["CPIAUCSL"].history_limit


def test_fred_series_mapping_matches_catalog():
    assert FRED_SERIES["DGS10"] == SERIES_CATALOG["DGS10"].name and set(FRED_SERIES) == set(SERIES_CATALOG)


# ---- units per change mode --------------------------------------------------------
def test_bp_mode_reports_basis_points():
    row = latest_vs_prior_release(obs([(date(2026, 10, 8), 4.10), (date(2026, 10, 9), 4.15)]), "DGS10")
    assert row["change"] == pytest.approx(5.0) and row["category"] == "rates"


def test_spread_in_bp_mode_handles_inversion():
    row = latest_vs_prior_release(obs([(date(2026, 10, 8), 0.05), (date(2026, 10, 9), -0.03)]), "T10Y2Y")
    assert row["change"] == pytest.approx(-8.0)


def test_pp_mode_unemployment_is_percentage_points_not_percent_of_percent():
    """Regression: the old table showed 4.1 -> 4.2 as +2.4%."""
    assert latest_vs_prior_release(monthly(2026, 7, [4.1, 4.2]), "UNRATE")["change"] == pytest.approx(0.1)


def test_abs_mode_payrolls_is_jobs_added_not_percent_of_level():
    assert latest_vs_prior_release(monthly(2026, 7, [159_000, 159_151]), "PAYEMS")["change"] == 151


def test_pct_mode_is_month_on_month_percent_and_safe_on_zero_prior():
    assert latest_vs_prior_release(monthly(2026, 7, [320.0, 321.6]), "CPIAUCSL")["change"] == pytest.approx(0.005)
    assert latest_vs_prior_release(monthly(2026, 7, [0.0, 5.0]), "CPIAUCSL")["change"] is None


# ---- YoY -------------------------------------------------------------------------
def test_yoy_matches_the_exact_calendar_month_one_year_earlier():
    row = latest_vs_prior_release(monthly(2025, 1, [300.0 + i for i in range(14)]), "CPIAUCSL")
    assert row["latest_date"] == date(2026, 2, 1)
    assert row["yoy"] == pytest.approx(313.0 / 301.0 - 1)


def test_yoy_none_without_history_or_with_a_gap_at_the_year_ago_month():
    assert latest_vs_prior_release(monthly(2026, 1, [300, 301, 302]), "CPIAUCSL")["yoy"] is None
    df = monthly(2025, 1, [300.0 + i for i in range(14)])
    df = df[df["date"] != date(2025, 2, 1)]  # no approximate matching
    assert latest_vs_prior_release(df, "CPIAUCSL")["yoy"] is None


def test_yoy_not_computed_for_series_that_do_not_ask_for_it():
    assert latest_vs_prior_release(monthly(2025, 1, [4.0 + 0.01 * i for i in range(14)]), "UNRATE")["yoy"] is None


# ---- edge cases -------------------------------------------------------------------
def test_empty_and_all_nan_return_none():
    assert latest_vs_prior_release(obs([]), "DGS10") is None
    assert latest_vs_prior_release(obs([(date(2026, 1, 1), np.nan)]), "DGS10") is None


def test_single_observation_still_returns_a_row():
    row = latest_vs_prior_release(obs([(date(2026, 10, 9), 4.15)]), "DGS10")
    assert row["prior_value"] is None and row["change"] is None and row["latest_value"] == 4.15


def test_unsorted_input_is_sorted_and_unknown_series_falls_back_to_percent_change():
    df = obs([(date(2026, 10, 9), 4.15), (date(2026, 10, 7), 4.00), (date(2026, 10, 8), 4.10)])
    row = latest_vs_prior_release(df, "DGS10")
    assert row["latest_value"] == 4.15 and row["prior_value"] == 4.10
    other = latest_vs_prior_release(monthly(2026, 1, [100.0, 110.0]), "SOMETHING_NEW")
    assert other["name"] == "SOMETHING_NEW" and other["category"] == "other" and other["change"] == pytest.approx(0.10)


# ---- summary ------------------------------------------------------------------------
def test_summary_filters_by_category_in_catalog_order_and_excludes_projections():
    by_series = {
        "T10Y2Y": obs([(date(2026, 10, 8), 0.4), (date(2026, 10, 9), 0.45)]),
        "DGS10": obs([(date(2026, 10, 8), 4.1), (date(2026, 10, 9), 4.15)]),
        "UNRATE": monthly(2026, 7, [4.1, 4.2]),
        "FEDTARMD": obs([(date(2026, 1, 1), 3.8), (date(2027, 1, 1), 3.6)]),
        "DGS2": obs([]),
    }
    assert [r["series_id"] for r in build_release_summary(by_series, category="rates")] == ["DGS10", "T10Y2Y"]
    assert [r["series_id"] for r in build_release_summary(by_series)] == ["DGS10", "T10Y2Y", "UNRATE"]


# ---- formatting ------------------------------------------------------------------------
@pytest.mark.parametrize("sid,value,expected", [
    ("DGS10", 4.254, "4.25%"), ("T10Y2Y", 0.45, "+45 bp"), ("T10Y2Y", -0.123, "-12 bp"),
    ("PAYEMS", 159_540, "159.54M"), ("ICSA", 231_000, "231k"), ("CPIAUCSL", 321.64, "321.6"),
    ("CES0500000003", 36.119, "$36.12"),
])
def test_format_level(sid, value, expected):
    assert format_level(SERIES_CATALOG[sid], value) == expected


@pytest.mark.parametrize("sid,value,expected", [
    ("DGS10", 5.0, "+5 bp"), ("DGS10", -12.4, "-12 bp"), ("UNRATE", 0.1, "+0.1 pp"),
    ("PAYEMS", 151, "+151k"), ("PAYEMS", -23, "-23k"), ("ICSA", 3_000, "+3k"), ("CPIAUCSL", 0.005, "+0.5%"),
])
def test_format_change(sid, value, expected):
    assert format_change(SERIES_CATALOG[sid], value) == expected


def test_formatters_render_missing_as_na():
    spec = SERIES_CATALOG["DGS10"]
    for bad in (None, float("nan")):
        assert format_level(spec, bad) == format_change(spec, bad) == format_yoy(bad) == "n/a"
    assert format_yoy(0.029) == "+2.9%"


# ---- FOMC projections ----------------------------------------------------------------------
def test_current_policy_rate_prefers_midpoint_then_effective():
    both = {"DFEDTARU": obs([(date(2026, 10, 9), 4.50)]), "DFEDTARL": obs([(date(2026, 10, 9), 4.25)]),
            "DFF": obs([(date(2026, 10, 9), 4.33)])}
    assert current_policy_rate(both) == (pytest.approx(4.375), "target-range midpoint")
    assert current_policy_rate({"DFF": both["DFF"]}) == (pytest.approx(4.33), "effective fed funds rate")
    assert current_policy_rate({}) is None


def test_sep_table_current_and_future_years_with_gap_and_longer_run():
    projections = obs([(date(2028, 1, 1), 3.4), (date(2025, 1, 1), 4.1),
                       (date(2026, 1, 1), 3.8), (date(2027, 1, 1), 3.6)])
    rows = build_sep_table(projections, obs([(date(2028, 1, 1), 3.0)]), policy_rate=4.375, as_of=date(2026, 10, 11))
    assert [r["label"] for r in rows] == ["2026 year-end", "2027 year-end", "2028 year-end", "Longer run"]
    assert rows[0]["vs_current_bp"] == pytest.approx(-57.5) and rows[-1]["year"] is None


def test_sep_table_without_policy_rate_or_data():
    rows = build_sep_table(obs([(date(2026, 1, 1), 3.8)]), None, policy_rate=None, as_of=date(2026, 10, 11))
    assert len(rows) == 1 and rows[0]["vs_current_bp"] is None
    assert build_sep_table(obs([]), None, 4.0, date(2026, 10, 11)) == []
    assert build_sep_table(None, None, 4.0, date(2026, 10, 11)) == []


# ---- market proxies ---------------------------------------------------------------------------
def test_proxies_report_gap_and_reading():
    by_series = {"DFF": _daily(7, [4.33] * 3), "DGS3MO": _daily(7, [4.30, 4.25, 4.00]),
                 "DGS2": _daily(7, [4.50, 4.50, 4.60])}
    rows = {r["name"]: r for r in build_market_proxies(by_series)}
    bill, two = rows["3M Treasury bill vs fed funds"], rows["2Y Treasury vs fed funds"]
    assert bill["gap_bp"] == pytest.approx(-33.0) and bill["reading"] == "cuts priced in"
    assert two["gap_bp"] == pytest.approx(27.0) and two["reading"] == "hikes priced in"
    assert bill["as_of"] == date(2026, 10, 9)


def test_proxy_inside_noise_band_reads_in_line_and_uses_shared_latest_date():
    [row] = build_market_proxies({"DFF": _daily(9, [4.33]), "DGS3MO": _daily(9, [4.38])})
    assert row["reading"] == "roughly in line"
    # DGS3MO lags DFF by a day: compare on the last date both have.
    [row] = build_market_proxies({"DFF": _daily(7, [4.33, 4.33, 4.00]), "DGS3MO": _daily(7, [4.30, 4.20])})
    assert row["as_of"] == date(2026, 10, 8) and row["gap_bp"] == pytest.approx(-13.0)


def test_proxies_skip_missing_inputs():
    assert build_market_proxies({}) == []
    assert build_market_proxies({"DGS3MO": _daily(9, [4.0])}) == []
    only = build_market_proxies({"DFF": _daily(9, [4.33]), "DGS2": _daily(9, [4.1])})
    assert [r["name"] for r in only] == ["2Y Treasury vs fed funds"]
