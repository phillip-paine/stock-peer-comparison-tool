"""Tests for data.transforms.dcf. Pure calculations, no DB/network."""
from __future__ import annotations

from datetime import date

import pytest

from src.peer_comparison_tool.data.transforms.dcf import (
    compute_dcf_scenarios,
    create_forecast_cashflow_dataframe,
)


def test_terminal_value_uses_decimal_rates_not_raw_percentages():
    """Regression test for bug #1: the terminal value denominator must be
    (discount_rate - terminal_rate) / 100, not the raw percentage-point
    difference -- the old formula understated it by ~100x."""
    _df, _discounted_cf, discounted_terminal_value = create_forecast_cashflow_dataframe(
        latest_free_cashflow=1000.0, growth_rate=5.0, discount_rate=10.0, terminal_rate=4.0,
        start_date=date(2024, 1, 1), future_years=5,
    )

    # Hand-computed with the correct Gordon Growth formula:
    # FCF_5 = 1000 * 1.05^5 = 1276.28...
    # terminal_value = FCF_5 * 1.04 / (0.10 - 0.04) = FCF_5 * 1.04 / 0.06
    # discounted_terminal_value = terminal_value / 1.10^5
    fcf_5 = 1000.0 * (1.05 ** 5)
    expected_terminal_value = fcf_5 * 1.04 / 0.06
    expected_discounted_terminal_value = expected_terminal_value / (1.10 ** 5)

    assert discounted_terminal_value == pytest.approx(expected_discounted_terminal_value, rel=1e-6)
    # Sanity check against the *old*, buggy formula to make sure this test
    # would actually have caught the regression: the old value is ~100x
    # smaller (denominator 6.0 vs 0.06 -- but numerator scale differs too,
    # so check the ratio is close to 100, not exactly, since only the
    # denominator scale changed).
    old_buggy_terminal_value = fcf_5 * 1.04 / (10.0 - 4.0)
    old_buggy_discounted = old_buggy_terminal_value / (1.10 ** 5)
    assert discounted_terminal_value / old_buggy_discounted == pytest.approx(100.0, rel=1e-6)


def test_raises_when_discount_rate_does_not_exceed_terminal_rate():
    with pytest.raises(ValueError, match="Discount rate"):
        create_forecast_cashflow_dataframe(
            latest_free_cashflow=1000.0, growth_rate=5.0, discount_rate=9.0, terminal_rate=9.6,
            start_date=date(2024, 1, 1),
        )


def test_forecast_dataframe_has_expected_shape_and_columns():
    df, _discounted_cf, _terminal = create_forecast_cashflow_dataframe(
        latest_free_cashflow=1000.0, growth_rate=5.0, discount_rate=10.0, terminal_rate=4.0,
        start_date=date(2024, 1, 1), future_years=5,
    )
    assert len(df) == 5
    assert list(df.columns) == ["date", "Discounted Forecast Free Cash Flow"]


def test_scenarios_use_their_own_terminal_value_not_base_case():
    """Regression test for bug #2: bear/bull dcf_value must be computed from
    their *own* discounted_terminal_value, not the base scenario's."""
    results = compute_dcf_scenarios(
        latest_free_cashflow=1000.0, growth_rate=5.0, discount_rate=12.0, terminal_rate=4.0,
        start_date=date(2024, 1, 1),
    )

    base, bear = results["base"], results["bear"]
    assert "error" not in base and "error" not in bear

    # Bear uses discount_rate*1.1=13.2%, terminal_rate*0.8=3.2% -- a
    # different (higher) discount rate and (lower) terminal rate than base,
    # so its own terminal value must differ from base's.
    assert bear["discounted_terminal_value"] != pytest.approx(base["discounted_terminal_value"])

    # And dcf_value must actually reflect that scenario's own terminal
    # value, not silently substitute the base one.
    assert bear["dcf_value"] == pytest.approx(bear["discounted_cf"] + bear["discounted_terminal_value"])
    assert bear["dcf_value"] != pytest.approx(bear["discounted_cf"] + base["discounted_terminal_value"])


def test_default_page_inputs_put_bull_scenario_in_invalid_state():
    """Documents the pre-existing issue the bug #2 fix surfaces: with this
    page's actual default inputs (5% / 10% / 8%) and its own bear/bull
    multipliers, Bull's discount rate (9%) ends up below its terminal
    growth rate (9.6%), which is invalid for Gordon Growth. This isn't a
    new bug introduced by the fix -- it was always true, just silently
    masked by bug #2 discarding Bull's own (broken) terminal value."""
    results = compute_dcf_scenarios(
        latest_free_cashflow=1000.0, growth_rate=5.0, discount_rate=10.0, terminal_rate=8.0,
        start_date=date(2024, 1, 1),
    )

    assert "error" not in results["base"]
    assert "error" not in results["bear"]
    assert "error" in results["bull"]


def test_compute_dcf_scenarios_bear_and_bull_rates_match_multipliers():
    results = compute_dcf_scenarios(
        latest_free_cashflow=1000.0, growth_rate=10.0, discount_rate=20.0, terminal_rate=2.0,
        start_date=date(2024, 1, 1),
    )
    # All three scenarios should succeed with these more generously-spaced
    # rates, letting us check bear/bull actually differ from base.
    assert set(results.keys()) == {"base", "bear", "bull"}
    for name in ("base", "bear", "bull"):
        assert "error" not in results[name], results[name]

    assert results["bear"]["dcf_value"] != pytest.approx(results["base"]["dcf_value"])
    assert results["bull"]["dcf_value"] != pytest.approx(results["base"]["dcf_value"])
