"""Reference tools: what's in the database, and how fresh it is."""
from __future__ import annotations

import difflib
from datetime import date
from typing import Any

import pandas as pd

from ...data.models import (
    AssetClassTimeSeries,
    BalanceSheetData,
    CashflowStatementData,
    ClusterMembership,
    CompanyInfo,
    DataStorageRecord,
    QuarterlyFinancialData,
    TickerMostRecentMetric,
    TickerTimeSeries,
)
from ..errors import ToolInputError
from ..read_repository import ReadRepository
from ..serialize import clamp, df_records, to_jsonable

MAX_COMPANIES = 500

# (label, model) for every dataset that has a date column.
_DATASETS = [
    ("stock_prices", TickerTimeSeries),
    ("asset_class_prices", AssetClassTimeSeries),
    ("quarterly_financials", QuarterlyFinancialData),
    ("balance_sheet", BalanceSheetData),
    ("cash_flow", CashflowStatementData),
    ("valuation_clusters", ClusterMembership),
]


def resolve_company(repo: ReadRepository, raw_ticker: str) -> dict[str, Any]:
    """The `company_info` row for `raw_ticker` (case-insensitive), or a
    ToolInputError that suggests close matches."""
    ticker = (raw_ticker or "").strip().upper()
    if not ticker:
        raise ToolInputError("ticker is required. Use list_companies(query=...) to find one.")
    info = repo.fetch_dataframe(CompanyInfo, ticker=ticker)
    if not info.empty:
        return to_jsonable(info.iloc[0].to_dict())
    raise ToolInputError(unknown_ticker_message(repo, ticker))


def unknown_ticker_message(repo: ReadRepository, ticker: str) -> str:
    companies = repo.fetch_dataframe(CompanyInfo)
    if companies.empty:
        return f"Unknown ticker {ticker!r}: the database has no companies yet (has the pipeline run?)."
    symbols = companies["ticker"].tolist()
    close = difflib.get_close_matches(ticker, symbols, n=5, cutoff=0.6)
    by_name = companies.loc[
        companies["name"].str.contains(ticker, case=False, regex=False, na=False), "ticker"
    ].tolist()[:5]
    hints = list(dict.fromkeys(close + by_name))
    if hints:
        return f"Unknown ticker {ticker!r}. Did you mean: {', '.join(hints)}? (list_companies(query=...) searches names too.)"
    return f"Unknown ticker {ticker!r}. Use list_companies(query=...) to search by ticker or company name."


def list_sectors(repo: ReadRepository) -> dict[str, Any]:
    """Sectors and sub-industries present in the database, with company counts.
    Peer comparisons are meaningful at the sub-industry level."""
    df = repo.fetch_dataframe(CompanyInfo)
    if df.empty:
        return {"company_count": 0, "sectors": []}
    df = df.assign(sub_industry=df["sub_industry"].fillna("Unclassified"))
    sectors = []
    for sector, group in df.groupby("sector"):
        subs = group.groupby("sub_industry").size().sort_index()
        sectors.append({
            "sector": sector,
            "company_count": int(len(group)),
            "sub_industries": [{"name": name, "company_count": int(n)} for name, n in subs.items()],
        })
    return to_jsonable({"company_count": int(len(df)), "sectors": sectors})


def list_companies(
    repo: ReadRepository,
    sector: str | None = None,
    sub_industry: str | None = None,
    query: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Companies in the database, filtered. `sector` / `sub_industry` match
    case-insensitively and exactly; `query` is a substring of ticker or name."""
    limit = clamp(limit, 1, MAX_COMPANIES)
    df = repo.fetch_dataframe(CompanyInfo)
    if not df.empty:
        if sector:
            df = df[df["sector"].str.casefold() == sector.strip().casefold()]
        if sub_industry:
            df = df[df["sub_industry"].fillna("").str.casefold() == sub_industry.strip().casefold()]
        if query:
            q = query.strip()
            hit = df["ticker"].str.contains(q, case=False, regex=False, na=False) | df["name"].str.contains(
                q, case=False, regex=False, na=False
            )
            df = df[hit]
        df = df.sort_values("ticker")
    total = int(len(df))
    return {
        "match_count": total,
        "returned": min(total, limit),
        "truncated": total > limit,
        "companies": df_records(df.head(limit), ["ticker", "name", "sector", "industry", "sub_industry"]),
    }


def _coverage(repo: ReadRepository, model: Any, ticker: str) -> dict[str, Any]:
    df = repo.fetch_dataframe(model, ticker=ticker)
    if df.empty:
        return {"rows": 0, "first_date": None, "latest_date": None}
    dates = pd.to_datetime(df["date"])
    return {"rows": int(len(df)), "first_date": dates.min(), "latest_date": dates.max()}


def company_profile(repo: ReadRepository, ticker: str) -> dict[str, Any]:
    """Everything stored about one company in a single call: identity, latest
    close, latest valuation snapshot, valuation-cluster label and data coverage."""
    info = resolve_company(repo, ticker)
    t = info["ticker"]

    latest = repo.recent_rows(TickerTimeSeries, 1, ticker=t)
    latest_price = None
    if not latest.empty:
        row = latest.iloc[0]
        latest_price = {"date": row["date"], "close": row["close_price"]}

    snapshot_df = repo.fetch_dataframe(TickerMostRecentMetric, ticker=t)
    snapshot = None
    if not snapshot_df.empty:
        snapshot = {k: v for k, v in snapshot_df.iloc[0].to_dict().items() if k != "ticker"}

    cluster_df = repo.recent_rows(ClusterMembership, 1, ticker=t)
    cluster = None
    if not cluster_df.empty:
        row = cluster_df.iloc[0]
        cluster = {"label": row["cluster_membership"], "as_of": row["date"]}

    return to_jsonable({
        "company": info,
        "latest_price": latest_price,
        "valuation_snapshot": snapshot,
        "valuation_cluster": cluster,
        "coverage": {
            "stock_prices": _coverage(repo, TickerTimeSeries, t),
            "quarterly_financials": _coverage(repo, QuarterlyFinancialData, t),
            "balance_sheet": _coverage(repo, BalanceSheetData, t),
            "cash_flow": _coverage(repo, CashflowStatementData, t),
        },
        "notes": [
            "valuation_snapshot has no date of its own: it is overwritten on each pipeline refresh, "
            "so it is as fresh as the last fetch (see data_freshness).",
            "See peer_valuation for how this company compares with its sub-industry peers.",
        ],
    })


def data_freshness(repo: ReadRepository, today: date | None = None) -> dict[str, Any]:
    """Latest observation date per dataset and the last pipeline fetch, so the
    caller can judge how current an answer is."""
    today = today or date.today()
    datasets = []
    for label, model in _DATASETS:
        latest = repo.max_date(model)
        datasets.append({
            "dataset": label,
            "latest_date": latest,
            "age_days": (today - latest).days if latest else None,
            "rows": repo.row_count(model),
        })
    last_fetch = repo.max_date(DataStorageRecord, "version_date")
    return to_jsonable({
        "today": today,
        "last_pipeline_fetch": last_fetch,
        "last_pipeline_fetch_age_days": (today - last_fetch).days if last_fetch else None,
        "companies": repo.row_count(CompanyInfo),
        "datasets": datasets,
        "notes": [
            "Prices are daily closes; the latest_date can trail 'today' over weekends and market holidays.",
            "Financial statements are as-reported quarterly/annual periods and update only when companies report.",
        ],
    })
