"""The tool functions against the seeded in-memory database (see conftest.py).

Every result is also pushed through json.dumps(allow_nan=False): that is the
contract with the MCP client, and it is what catches NaN / inf / numpy leaks.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from peer_comparison_tool.data.models import TickerMostRecentMetric
from peer_comparison_tool.mcp_server.errors import ToolInputError
from peer_comparison_tool.mcp_server.tools import fundamentals, prices, reference, valuation

from .conftest import DAYS, LAST_DAY


def _json(result):
    return json.loads(json.dumps(result, allow_nan=False))


# ---- reference ---------------------------------------------------------------

def test_list_sectors_groups_sub_industries_and_labels_missing_ones(repo):
    out = _json(reference.list_sectors(repo))
    by_sector = {s["sector"]: s for s in out["sectors"]}
    assert out["company_count"] == 5
    assert by_sector["Tech"]["sub_industries"] == [{"name": "Widgets", "company_count": 4}]
    assert by_sector["Energy"]["sub_industries"] == [{"name": "Unclassified", "company_count": 1}]


def test_list_companies_filters_case_insensitively_and_flags_truncation(repo):
    out = _json(reference.list_companies(repo, sector="tech"))
    assert [c["ticker"] for c in out["companies"]] == ["AAA", "BBB", "CCC", "DDD"]

    assert _json(reference.list_companies(repo, query="gamma"))["companies"][0]["ticker"] == "CCC"
    assert _json(reference.list_companies(repo, sub_industry="WIDGETS"))["match_count"] == 4

    limited = _json(reference.list_companies(repo, sector="Tech", limit=2))
    assert (limited["match_count"], limited["returned"], limited["truncated"]) == (4, 2, True)


def test_company_profile_has_latest_price_snapshot_latest_cluster_and_coverage(repo):
    out = _json(reference.company_profile(repo, "aaa"))          # case-insensitive
    assert out["company"]["name"] == "Alpha Corp"
    assert out["latest_price"] == {"date": LAST_DAY.isoformat(), "close": 139.0}
    assert out["valuation_snapshot"]["price_eps_ratio"] == 25.0
    # Two cluster runs are stored; the newer one wins.
    assert out["valuation_cluster"] == {"label": "Not cluster member", "as_of": "2026-10-01"}
    assert out["coverage"]["stock_prices"]["rows"] == 40
    assert out["coverage"]["quarterly_financials"]["latest_date"] == "2026-06-30"


def test_company_with_no_data_still_profiles(repo):
    out = _json(reference.company_profile(repo, "EEE"))
    assert out["latest_price"] is None and out["valuation_snapshot"] is None
    assert out["coverage"]["stock_prices"]["rows"] == 0


def test_unknown_ticker_suggests_close_matches_and_name_hits(repo):
    with pytest.raises(ToolInputError, match="AAA"):
        reference.company_profile(repo, "AAX")
    with pytest.raises(ToolInputError, match="DDD"):
        reference.company_profile(repo, "delta")      # matches the company NAME of DDD
    with pytest.raises(ToolInputError, match="ticker is required"):
        reference.company_profile(repo, "  ")


def test_data_freshness_reports_age_and_last_fetch(repo):
    out = _json(reference.data_freshness(repo, today=date(2026, 10, 20)))
    by_name = {d["dataset"]: d for d in out["datasets"]}
    assert by_name["stock_prices"]["latest_date"] == "2026-10-16"
    assert by_name["stock_prices"]["age_days"] == 4
    assert by_name["stock_prices"]["rows"] == 40
    assert by_name["cash_flow"]["latest_date"] == "2025-12-31"
    assert out["last_pipeline_fetch"] == "2026-10-15" and out["last_pipeline_fetch_age_days"] == 5
    assert out["companies"] == 5


def test_data_freshness_on_an_empty_table_is_null_not_an_error(repo):
    from peer_comparison_tool.data.models import ClusterMembership
    from sqlalchemy import delete
    repo._session.execute(delete(ClusterMembership))
    out = _json(reference.data_freshness(repo, today=date(2026, 10, 20)))
    clusters = {d["dataset"]: d for d in out["datasets"]}["valuation_clusters"]
    assert clusters["latest_date"] is None and clusters["age_days"] is None and clusters["rows"] == 0


# ---- prices ------------------------------------------------------------------

def test_price_history_returns_latest_rows_oldest_first_with_summary(repo):
    out = _json(prices.price_history(repo, "AAA", observations=5))
    assert out["source"] == "stock" and out["as_of"] == LAST_DAY.isoformat()
    assert [r["close"] for r in out["rows"]] == [135.0, 136.0, 137.0, 138.0, 139.0]
    assert out["summary"]["period_return"] == pytest.approx(139 / 135 - 1)
    assert (out["summary"]["low_close"], out["summary"]["high_close"]) == (135.0, 139.0)


def test_price_history_caps_observations(repo):
    out = _json(prices.price_history(repo, "AAA", observations=10_000))
    assert out["observations"] == 40
    assert _json(prices.price_history(repo, "AAA", observations=0))["observations"] == 1


def test_weekly_rows_are_real_trading_days_not_period_ends(repo):
    out = _json(prices.price_history(repo, "AAA", observations=100, frequency="weekly"))
    dates = [r["date"] for r in out["rows"]]
    assert 0 < len(dates) < 40
    assert set(dates) <= {d.isoformat() for d in DAYS}
    assert dates[-1] == LAST_DAY.isoformat()          # the latest observation is always kept
    monthly = _json(prices.price_history(repo, "AAA", observations=100, frequency="monthly"))
    assert len(monthly["rows"]) < len(dates)


def test_price_history_resolves_assets_by_symbol_or_friendly_name(repo):
    by_name = _json(prices.price_history(repo, "us10y_yield", observations=3))
    assert by_name["source"] == "asset_class" and by_name["asset_class"] == "rate"
    assert any("percentage points" in n for n in by_name["notes"])

    etf = _json(prices.price_history(repo, "spy", observations=2))          # symbol -> S&P500_ETF
    assert etf["instrument"] == "S&P500_ETF" and etf["rows"][-1]["close"] == 539.0
    assert not any("percentage points" in n for n in etf["notes"])


def test_price_history_rejects_bad_input_with_actionable_messages(repo):
    with pytest.raises(ToolInputError, match="frequency must be one of"):
        prices.price_history(repo, "AAA", frequency="hourly")
    with pytest.raises(ToolInputError, match="Tracked non-stock series"):
        prices.price_history(repo, "NOPE")
    with pytest.raises(ToolInputError, match="ticker is required"):
        prices.price_history(repo, "")


def test_asset_moves_computes_fractions_and_filters_by_class(repo):
    out = _json(prices.asset_moves(repo))
    etf = next(a for a in out["assets"] if a["ticker"] == "S&P500_ETF")
    assert etf["symbol"] == "SPY" and etf["asset_class"] == "etf"
    assert etf["latest_price"] == 539.0 and etf["latest_date"] == LAST_DAY.isoformat()
    assert etf["change_1d"] == pytest.approx(539 / 538 - 1)
    assert etf["change_1w"] == pytest.approx(539 / 534 - 1)           # 5 trading days back
    assert etf["change_1m"] == pytest.approx(539 / 518 - 1)           # 21 trading days back

    only_rates = _json(prices.asset_moves(repo, asset_class="RATE"))
    assert [a["ticker"] for a in only_rates["assets"]] == ["US10Y_Yield"]
    with pytest.raises(ToolInputError, match="asset_class must be one of"):
        prices.asset_moves(repo, asset_class="stocks")


# ---- fundamentals ------------------------------------------------------------

def test_quarterly_financials_oldest_first_with_yoy_merged_and_nan_as_null(repo):
    out = _json(fundamentals.quarterly_financials(repo, "AAA", quarters=2))
    assert [r["quarter_reporting"] for r in out["rows"]] == ["2026Q1", "2026Q2"]
    assert out["as_of"] == "2026-06-30"
    latest = out["rows"][-1]
    assert latest["basic_eps_yoy"] == 0.5 and latest["net_margin"] is None   # NaN -> null
    assert out["rows"][0]["basic_eps_yoy"] is None                            # no YoY row for that quarter
    assert "ticker" not in latest
    assert any("PERCENT" in n for n in out["notes"])

    no_yoy = _json(fundamentals.quarterly_financials(repo, "AAA", include_yoy=False))
    assert "basic_eps_yoy" not in no_yoy["rows"][0] and no_yoy["periods"] == 3


def test_balance_sheet_and_cash_flow(repo):
    bs = _json(fundamentals.balance_sheet(repo, "AAA", periods=1))
    assert bs["periods"] == 1 and bs["rows"][0]["annual_reporting"] == "2026"
    assert any("per-share" in n for n in bs["notes"])        # the misleading-name caveat travels with the data

    cf = _json(fundamentals.cash_flow(repo, "AAA"))
    assert cf["rows"][0]["free_cash_flow"] == 5e8


def test_financials_for_a_company_without_data_are_empty_not_errors(repo):
    out = _json(fundamentals.quarterly_financials(repo, "EEE"))
    assert out["periods"] == 0 and out["rows"] == [] and out["as_of"] is None


# ---- valuation ---------------------------------------------------------------

def test_peer_valuation_percentile_is_position_among_the_other_companies(repo):
    out = _json(valuation.peer_valuation(repo, "AAA"))
    pe = out["metrics"]["price_eps_ratio"]
    # peers 20 / 30 / 40: AAA's 25 is above one of three -> 33.3
    assert pe["value"] == 25.0 and pe["peer_count"] == 3 and pe["peer_median"] == 30.0
    assert (pe["peer_min"], pe["peer_max"]) == (20.0, 40.0)
    assert pe["percentile"] == pytest.approx(100 / 3)
    assert out["peer_count"] == 3 and out["sub_industry"] == "Widgets"
    assert out["cluster"] == {"label": "Not cluster member", "as_of": "2026-10-01"}
    # Largest market cap first, company itself excluded, cluster label attached.
    assert [p["ticker"] for p in out["peers"]] == ["BBB", "CCC", "DDD"]
    assert out["peers"][0]["cluster"] == "Cluster member" and out["peers"][2]["cluster"] is None


def test_percentile_needs_enough_peers_with_a_value(repo):
    out = _json(valuation.peer_valuation(repo, "AAA"))
    ptb = out["metrics"]["price_to_book"]            # DDD has none -> only 2 peers
    assert ptb["peer_count"] == 2 and ptb["peer_median"] == 3.5 and ptb["percentile"] is None


def test_infinite_pe_is_excluded_from_peer_statistics(repo):
    repo.upsert(TickerMostRecentMetric, [
        {"ticker": "DDD", "market_cap": 5e10, "price_eps_ratio": float("inf"), "price_to_book": None,
         "return_on_equity": 0.4, "debt_to_equity_ratio": 100.0, "profit_margin": 0.25,
         "enterprise_to_ebitda": 16.0, "latest_eps": 6.0, "enterprise_value": 5.1e10},
    ], mode="replace")
    pe = _json(valuation.peer_valuation(repo, "AAA"))["metrics"]["price_eps_ratio"]
    assert pe["peer_count"] == 2 and pe["peer_median"] == 25.0 and pe["peer_max"] == 30.0   # 20, 30 only
    assert pe["percentile"] is None                                                           # 2 < 3 peers

    ddd = _json(valuation.peer_valuation(repo, "DDD"))["metrics"]["price_eps_ratio"]
    assert ddd["value"] is None                      # inf is "no meaningful P/E", not a number to rank


def test_peer_valuation_edge_cases(repo):
    with pytest.raises(ToolInputError, match="no sub_industry"):
        valuation.peer_valuation(repo, "EEE")
    assert len(_json(valuation.peer_valuation(repo, "AAA", max_peers=1))["peers"]) == 1
    assert _json(valuation.peer_valuation(repo, "AAA", max_peers=1))["peers_truncated"] is True


def test_misc_sub_industry_is_flagged_as_not_a_real_peer_group(repo):
    from peer_comparison_tool.data.models import CompanyInfo
    repo.upsert(CompanyInfo, [{"ticker": "ZZZ", "name": "Zed", "sector": "Misc.", "industry": None,
                               "sub_industry": "Misc."}])
    out = _json(valuation.peer_valuation(repo, "ZZZ"))
    assert out["metrics"] is None                     # no snapshot stored for ZZZ
    assert any("NOT a meaningful peer group" in n for n in out["notes"])


def test_valuation_clusters_by_ticker_and_by_sub_industry(repo):
    one = _json(valuation.valuation_clusters(repo, ticker="AAA"))
    assert one["cluster"] == "Not cluster member" and one["as_of"] == "2026-10-01"

    group = _json(valuation.valuation_clusters(repo, sub_industry="widgets"))
    assert group["company_count"] == 4
    assert (group["cluster_members"], group["not_cluster_members"], group["unlabelled"]) == (2, 1, 1)
    labels = {c["ticker"]: c["cluster"] for c in group["companies"]}
    assert labels == {"AAA": "Not cluster member", "BBB": "Cluster member", "CCC": "Cluster member", "DDD": None}


def test_valuation_clusters_argument_validation(repo):
    with pytest.raises(ToolInputError, match="exactly one"):
        valuation.valuation_clusters(repo)
    with pytest.raises(ToolInputError, match="exactly one"):
        valuation.valuation_clusters(repo, ticker="AAA", sub_industry="Widgets")
    with pytest.raises(ToolInputError, match="Widgets"):
        valuation.valuation_clusters(repo, sub_industry="Widgetz")      # suggestion includes the real name
