from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from peer_comparison_tool.data.transforms.ticker_financials import (
    transform_balance_sheet,
    transform_cashflow,
    transform_company_info,
    transform_price_history,
    transform_quarterly_financials,
    transform_recent_metrics,
)


def _quarterly_raw(rows: dict[str, list[float]], dates: list[str]) -> pd.DataFrame:
    columns = pd.to_datetime(dates)
    return pd.DataFrame(rows, index=list(rows.keys())).set_axis(columns, axis=1) \
        if False else pd.DataFrame.from_dict(
            {k: v for k, v in rows.items()}, orient="index", columns=columns
        )


class TestTransformQuarterlyFinancials:
    def _base_rows(self):
        # index=line items, columns=report dates -- matches yfinance's actual shape
        return {
            "Basic EPS": [1.5, 1.2],
            "Operating Income": [500.0, 400.0],
            "Total Revenue": [2000.0, 1800.0],
            "Gross Profit": [800.0, 700.0],
            "Net Income": [300.0, 250.0],
            "EBITDA": [600.0, 500.0],
        }

    def test_computes_margins_correctly(self):
        raw = _quarterly_raw(self._base_rows(), ["2026-03-31", "2025-12-31"])
        result = transform_quarterly_financials(raw, "AAPL")

        assert len(result) == 2
        row = result[result["date"] == date(2026, 3, 31)].iloc[0]
        assert row["gross_margin"] == pytest.approx(800.0 / 2000.0 * 100)
        assert row["operating_margin"] == pytest.approx(500.0 / 2000.0 * 100)
        assert row["net_margin"] == pytest.approx(300.0 / 2000.0 * 100)
        assert row["ebitda_margin"] == pytest.approx(600.0 / 2000.0 * 100)
        assert row["operating_income_mm"] == pytest.approx(500.0 / 1_000_000)
        assert row["ticker"] == "AAPL"

    def test_quarter_reporting_label_shifts_back_a_month_first(self):
        raw = _quarterly_raw(self._base_rows(), ["2026-03-31", "2025-12-31"])
        result = transform_quarterly_financials(raw, "AAPL")
        row = result[result["date"] == date(2026, 3, 31)].iloc[0]
        # 2026-03-31 minus 1 month = 2026-02-28 -> Q1 2026
        assert row["quarter_reporting"] == "2026_1"

    def test_falls_back_to_diluted_eps_when_basic_eps_missing(self):
        rows = self._base_rows()
        del rows["Basic EPS"]
        rows["Diluted EPS"] = [1.4, 1.1]
        raw = _quarterly_raw(rows, ["2026-03-31", "2025-12-31"])
        result = transform_quarterly_financials(raw, "AAPL")
        row = result[result["date"] == date(2026, 3, 31)].iloc[0]
        assert row["basic_eps"] == pytest.approx(1.4)

    def test_falls_back_to_diluted_eps_none_gives_nan_then_zero(self):
        rows = self._base_rows()
        del rows["Basic EPS"]
        raw = _quarterly_raw(rows, ["2026-03-31", "2025-12-31"])
        result = transform_quarterly_financials(raw, "AAPL")
        row = result[result["date"] == date(2026, 3, 31)].iloc[0]
        assert row["basic_eps"] == 0.0

    def test_bank_uses_net_interest_income_for_gross_profit(self):
        rows = self._base_rows()
        del rows["Gross Profit"]
        rows["Net Interest Income"] = [900.0, 850.0]
        raw = _quarterly_raw(rows, ["2026-03-31", "2025-12-31"])
        result = transform_quarterly_financials(raw, "JPM")
        row = result[result["date"] == date(2026, 3, 31)].iloc[0]
        assert row["gross_margin"] == pytest.approx(900.0 / 2000.0 * 100)

    def test_zero_revenue_gives_zero_margins_not_inf(self):
        rows = self._base_rows()
        rows["Total Revenue"] = [0.0, 0.0]
        raw = _quarterly_raw(rows, ["2026-03-31", "2025-12-31"])
        result = transform_quarterly_financials(raw, "AAPL")
        row = result[result["date"] == date(2026, 3, 31)].iloc[0]
        assert row["gross_margin"] == 0.0

    def test_missing_required_row_with_no_fallback_returns_empty(self):
        rows = self._base_rows()
        del rows["Total Revenue"]
        raw = _quarterly_raw(rows, ["2026-03-31", "2025-12-31"])
        result = transform_quarterly_financials(raw, "AAPL")
        assert result.empty

    def test_empty_input_returns_empty_with_expected_columns(self):
        result = transform_quarterly_financials(pd.DataFrame(), "AAPL")
        assert result.empty
        assert "quarter_reporting" in result.columns


class TestTransformBalanceSheet:
    def _standard_raw(self):
        rows = {
            "OrdinarySharesNumber": [1000.0],
            "StockholdersEquity": [5000.0],
            "TotalLiabilitiesNetMinorityInterest": [3000.0],
            "CurrentAssets": [4000.0],
        }
        return pd.DataFrame.from_dict(rows, orient="index", columns=pd.to_datetime(["2026-01-01"]))

    def test_computes_ratios_for_standard_company(self):
        result = transform_balance_sheet(self._standard_raw(), "AAPL")
        row = result.iloc[0]
        assert row["quick_ratio"] == pytest.approx(4000.0 / 3000.0)
        assert row["equity_ratio"] == pytest.approx((4000.0 - 3000.0) / 1000.0)
        assert row["debt_to_equity_ratio"] == pytest.approx(3000.0 / 5000.0)

    def test_annual_reporting_year_shifts_forward_three_months(self):
        result = transform_balance_sheet(self._standard_raw(), "AAPL")
        # 2026-01-01 + 3 months = 2026-04-01 -> still 2026
        assert result.iloc[0]["annual_reporting"] == "2026"

    def test_quick_ratio_uses_inventory_when_present(self):
        rows = {
            "OrdinarySharesNumber": [1000.0],
            "StockholdersEquity": [5000.0],
            "TotalLiabilitiesNetMinorityInterest": [3000.0],
            "CurrentAssets": [4000.0],
            "Inventory": [1000.0],
        }
        raw = pd.DataFrame.from_dict(rows, orient="index", columns=pd.to_datetime(["2026-01-01"]))
        result = transform_balance_sheet(raw, "AAPL")
        assert result.iloc[0]["quick_ratio"] == pytest.approx((4000.0 - 1000.0) / 3000.0)

    def test_financial_institution_gets_a_quick_ratio_from_synthesized_liabilities(self):
        """Regression test for the original bug: Quick Ratio was only computed
        when TotalLiabilitiesNetMinorityInterest was reported directly, so
        any ticker needing it synthesized (typically banks) silently got no
        Quick Ratio at all."""
        rows = {
            "OrdinarySharesNumber": [1000.0],
            "StockholdersEquity": [5000.0],
            "TotalDeposits": [2000.0],
            "AccountsPayable": [500.0],
            "CashAndCashEquivalents": [1500.0],
            "Receivables": [800.0],
        }
        raw = pd.DataFrame.from_dict(rows, orient="index", columns=pd.to_datetime(["2026-01-01"]))
        result = transform_balance_sheet(raw, "JPM")

        row = result.iloc[0]
        expected_liabilities = 2000.0 + 500.0  # TotalDeposits + AccountsPayable
        expected_current_assets = 1500.0 + 800.0  # Cash + Receivables
        assert not pd.isna(row["quick_ratio"])
        assert row["quick_ratio"] == pytest.approx(expected_current_assets / expected_liabilities)
        assert row["total_liabilities_net_minority_interest"] == pytest.approx(expected_liabilities)

    def test_empty_input_returns_empty_with_expected_columns(self):
        result = transform_balance_sheet(pd.DataFrame(), "AAPL")
        assert result.empty
        assert "quick_ratio" in result.columns


class TestTransformCashflow:
    def test_extracts_expected_columns(self):
        rows = {
            "Free Cash Flow": [100.0],
            "Operating Cash Flow": [150.0],
            "Capital Expenditure": [-50.0],
        }
        raw = pd.DataFrame.from_dict(rows, orient="index", columns=pd.to_datetime(["2026-01-01"]))
        result = transform_cashflow(raw, "AAPL")
        row = result.iloc[0]
        assert row["free_cash_flow"] == 100.0
        assert row["ticker"] == "AAPL"

    def test_missing_column_is_nan_not_dropped(self):
        rows = {"Free Cash Flow": [100.0]}
        raw = pd.DataFrame.from_dict(rows, orient="index", columns=pd.to_datetime(["2026-01-01"]))
        result = transform_cashflow(raw, "AAPL")
        assert pd.isna(result.iloc[0]["operating_cash_flow"])

    def test_empty_input(self):
        result = transform_cashflow(pd.DataFrame(), "AAPL")
        assert result.empty


class TestTransformPriceHistory:
    def test_indexes_to_100_at_first_value(self):
        raw = pd.DataFrame(
            {"Close": [50.0, 55.0, 60.0]},
            index=pd.date_range("2026-01-01", periods=3, freq="D", tz="America/New_York", name="Date"),
        )
        result = transform_price_history(raw, "AAPL")
        assert result.iloc[0]["close_price_indexed"] == pytest.approx(100.0)
        assert result.iloc[2]["close_price_indexed"] == pytest.approx(60.0 / 50.0 * 100)

    def test_strips_timezone(self):
        raw = pd.DataFrame(
            {"Close": [50.0]},
            index=pd.date_range("2026-01-01", periods=1, freq="D", tz="America/New_York", name="Date"),
        )
        result = transform_price_history(raw, "AAPL")
        assert result.iloc[0]["date"] == date(2026, 1, 1)

    def test_empty_input(self):
        result = transform_price_history(pd.DataFrame(), "AAPL")
        assert result.empty


class TestTransformCompanyInfo:
    def test_returns_dict_when_sector_present(self):
        info = {"sector": "Technology", "industry": "Hardware"}
        result = transform_company_info(info, "AAPL", "Apple Inc.", "Tech Hardware")
        assert result == {
            "ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology",
            "industry": "Hardware", "sub_industry": "Tech Hardware",
        }

    def test_returns_none_when_sector_missing(self):
        info = {"industry": "Hardware"}
        result = transform_company_info(info, "AAPL", "Apple Inc.", "Tech Hardware")
        assert result is None


class TestTransformRecentMetrics:
    def test_computes_latest_eps_from_net_income_and_shares(self):
        info = {"netIncomeToCommon": 1_000_000.0, "sharesOutstanding": 500_000.0}
        result = transform_recent_metrics(info, "AAPL")
        assert result["latest_eps"] == pytest.approx(2.0)

    def test_missing_shares_outstanding_does_not_raise(self):
        info = {"netIncomeToCommon": 1_000_000.0}
        result = transform_recent_metrics(info, "AAPL")
        assert result["latest_eps"] is None

    def test_infinity_string_trailing_pe_becomes_inf(self):
        info = {"trailingPE": "Infinity"}
        result = transform_recent_metrics(info, "AAPL")
        assert result["price_eps_ratio"] == np.inf

    def test_rounds_values(self):
        info = {"priceToBook": 3.14159}
        result = transform_recent_metrics(info, "AAPL")
        assert result["price_to_book"] == 3.14
