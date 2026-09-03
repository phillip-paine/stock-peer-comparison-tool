"""
Pure, DB-free discounted-cash-flow (DCF) scenario calculations.

Extracted out of `comparison_tool/discounted_cashflow_model_page.py` (same
pattern as `pairs_trading.py`) so the actual math is testable without a Dash
app, and so the two valuation bugs found while tracing that page have a
regression test each rather than just a fix.

Bugs found and fixed here:

1. **Terminal value formula mixed percentage-points and decimals.** The
   Gordon Growth terminal value formula is `FCF_next * (1+g) / (r - g)`
   with `r` (discount rate) and `g` (terminal growth rate) as *decimals*.
   The original passed `discount_rate` and `terminal_rate` in as raw
   percentages (e.g. `10`, `8`) and used `(discount_rate - terminal_rate)`
   — i.e. `2` — directly as the denominator, instead of `0.02`. That
   understates the discounted terminal value by roughly 100x, and since
   terminal value is usually the majority of a DCF's total, this was the
   single biggest source of error in the page's output.
2. **Bear and Bull scenarios reused the Base scenario's terminal value.**
   Each scenario computes its own terminal value internally (different
   discount/terminal rates), but the original discarded the bear/bull ones
   and added the *base* case's terminal value to every scenario's
   discounted cash flow total. Since terminal value dominates the total,
   this collapsed almost all of the intended spread between bear/base/bull.
   `compute_dcf_scenarios` below uses each scenario's own terminal value.

One thing the fix above *surfaces* rather than causes: with this page's own
default inputs (growth=5%, discount=10%, terminal=8%) and its own bear/bull
multipliers, the Bull scenario ends up with `discount_rate * 0.9 = 9%` and
`terminal_rate * 1.2 = 9.6%` — i.e. a terminal growth rate *above* the
discount rate, which the Gordon Growth formula can't handle (it divides by
a negative number, producing a nonsensical negative "value"). The original
code never surfaced this because bug #2 meant the Bull scenario's own
(broken) terminal value was silently discarded and replaced with the Base
scenario's. `create_forecast_cashflow_dataframe` now raises `ValueError`
in this situation instead of returning a nonsensical number, and
`compute_dcf_scenarios` catches that per-scenario so one bad scenario
doesn't take down the whole page — see its docstring for how that surfaces
to the caller. This is worth knowing about, not something to paper over:
it means the *default* multipliers on this page put Bull in an invalid
state, and either the multipliers or the default rates need adjusting for
Bull to produce a usable number out of the box.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

CF_FUTURE_YEARS = 5

# Same bear/bull scenario multipliers as the original page.
BEAR_MULTIPLIERS = {"growth_rate": 0.8, "discount_rate": 1.1, "terminal_rate": 0.8}
BULL_MULTIPLIERS = {"growth_rate": 1.2, "discount_rate": 0.9, "terminal_rate": 1.2}


def create_forecast_cashflow_dataframe(
    latest_free_cashflow: float,
    growth_rate: float,
    discount_rate: float,
    terminal_rate: float,
    start_date: date,
    future_years: int = CF_FUTURE_YEARS,
) -> tuple[pd.DataFrame, float, float]:
    """Forecast free cash flow forward `future_years` years at `growth_rate`,
    discount each year back at `discount_rate`, and compute a Gordon Growth
    terminal value at `terminal_rate`. Rates are percentages (`10` means
    10%), matching the dashboard's input fields.

    Returns `(forecast_df, total_discounted_cashflow, discounted_terminal_value)`.
    Raises `ValueError` if `discount_rate <= terminal_rate` — the terminal
    value formula is undefined (division by zero) or nonsensical (negative)
    otherwise; see the module docstring for when this actually happens with
    this page's own default inputs.
    """
    if discount_rate <= terminal_rate:
        raise ValueError(
            f"Discount rate ({discount_rate}%) must exceed the terminal growth rate "
            f"({terminal_rate}%) for the Gordon Growth terminal value to be finite and positive."
        )

    future_cashflows = []
    discounted_future_cashflows = []
    for year in range(1, future_years + 1):
        future_cashflows.append(latest_free_cashflow * ((1 + growth_rate / 100) ** year))
        discounted_future_cashflows.append(future_cashflows[-1] / ((1 + discount_rate / 100) ** year))

    terminal_value = future_cashflows[-1] * (1 + terminal_rate / 100) / ((discount_rate - terminal_rate) / 100)
    discounted_terminal_value = terminal_value / ((1 + discount_rate / 100) ** future_years)
    total_discounted_future_cashflows = sum(discounted_future_cashflows)

    forecast_df = pd.DataFrame({
        # 'YE' (year-end), not the original 'Y' -- that alias was removed
        # in current pandas and raised outright on every call.
        "date": pd.date_range(pd.Timestamp(start_date).strftime("%Y-%m-%d"), periods=future_years, freq="YE"),
        "Discounted Forecast Free Cash Flow": discounted_future_cashflows,
    })
    return forecast_df, total_discounted_future_cashflows, discounted_terminal_value


def compute_dcf_scenarios(
    latest_free_cashflow: float,
    growth_rate: float,
    discount_rate: float,
    terminal_rate: float,
    start_date: date,
    future_years: int = CF_FUTURE_YEARS,
) -> dict[str, dict[str, Any]]:
    """Run base/bear/bull DCF scenarios. Each scenario dict has either:
    - `{"cashflow_df", "discounted_cf", "discounted_terminal_value", "dcf_value"}`
      on success (`dcf_value` = `discounted_cf` + `discounted_terminal_value`), or
    - `{"error": "<message>"}` if that scenario's rates put the terminal
      value formula in an invalid state (see module docstring) — this
      scenario is skipped rather than silently wrong, and the caller
      decides how to surface a partial result.
    """
    base_rates = {"growth_rate": growth_rate, "discount_rate": discount_rate, "terminal_rate": terminal_rate}
    scenario_rates = {
        "base": base_rates,
        "bear": {k: v * BEAR_MULTIPLIERS[k] for k, v in base_rates.items()},
        "bull": {k: v * BULL_MULTIPLIERS[k] for k, v in base_rates.items()},
    }

    results: dict[str, dict[str, Any]] = {}
    for name, rates in scenario_rates.items():
        try:
            cashflow_df, discounted_cf, discounted_terminal_value = create_forecast_cashflow_dataframe(
                latest_free_cashflow, rates["growth_rate"], rates["discount_rate"], rates["terminal_rate"],
                start_date, future_years,
            )
        except ValueError as exc:
            results[name] = {"error": str(exc)}
            continue
        results[name] = {
            "cashflow_df": cashflow_df,
            "discounted_cf": discounted_cf,
            "discounted_terminal_value": discounted_terminal_value,
            "dcf_value": discounted_cf + discounted_terminal_value,
        }
    return results
