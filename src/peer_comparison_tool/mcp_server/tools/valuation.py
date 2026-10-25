"""Valuation tools: where a company sits against its sub-industry peers, and
the stored DBSCAN valuation-cluster labels."""
from __future__ import annotations

import difflib
from typing import Any

import numpy as np
import pandas as pd

from ...data.models import CompanyInfo
from ..errors import ToolInputError
from ..read_repository import ReadRepository
from ..serialize import clamp, df_records, to_jsonable
from .reference import resolve_company

METRICS = [
    "market_cap", "price_eps_ratio", "price_to_book", "return_on_equity", "debt_to_equity_ratio",
    "profit_margin", "enterprise_to_ebitda", "latest_eps", "enterprise_value",
]
# Peers shown in the table, and the columns shown for each.
PEER_COLUMNS = ["ticker", "name", "market_cap", "price_eps_ratio", "enterprise_to_ebitda", "cluster"]
MIN_PEERS_FOR_PERCENTILE = 3
MAX_PEERS = 50

SNAPSHOT_NOTES = [
    "Units come from the yfinance snapshot: return_on_equity and profit_margin are FRACTIONS (0.25 = 25%), "
    "unlike the quarterly margins in quarterly_financials, which are percent.",
    "debt_to_equity_ratio here is yfinance's debtToEquity (percentage-style figure), not the plain "
    "liabilities / equity ratio on the balance_sheet tool.",
    "price_eps_ratio is null for companies with no meaningful trailing P/E (the pipeline stores +inf for "
    "loss-making companies; it is dropped here, not ranked).",
]
CLUSTER_MEANING = (
    "'Cluster member' = sits in a dense group of valuation-similar peers (DBSCAN on P/E, EPS, ROE, EV/EBITDA, "
    "debt/equity, profit margin within its sub-industry). 'Not cluster member' = a valuation outlier OR missing "
    "inputs OR too few peers to form a cluster -- the stored label does not distinguish these."
)


def _metric_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Replace +/-inf with NaN so they are excluded from medians and ranks."""
    out = df.copy()
    cols = [c for c in METRICS if c in out.columns]
    out[cols] = out[cols].replace([np.inf, -np.inf], np.nan)
    return out


def _latest_clusters(repo: ReadRepository) -> pd.DataFrame:
    latest = repo.latest_cluster_membership()
    if latest.empty:
        return pd.DataFrame(columns=["ticker", "cluster", "cluster_as_of"])
    return latest.rename(columns={"cluster_membership": "cluster", "date": "cluster_as_of"})[
        ["ticker", "cluster", "cluster_as_of"]
    ]


def _metric_stats(company_value: Any, peer_values: pd.Series) -> dict[str, Any]:
    """Company value against the OTHER companies' values for one metric.

    `percentile` is the mid-rank share of peers with a lower value (ties count
    half), 0-100: 100 = highest in the group. It is a position, not a verdict --
    whether high is good depends on the metric. None when fewer than
    MIN_PEERS_FOR_PERCENTILE peers have a value, or the company has none.
    """
    peers = peer_values.dropna().astype(float)
    value = None if company_value is None or pd.isna(company_value) else float(company_value)
    percentile = None
    if value is not None and len(peers) >= MIN_PEERS_FOR_PERCENTILE:
        below = (peers < value).sum()
        equal = (peers == value).sum()
        percentile = 100.0 * (below + 0.5 * equal) / len(peers)
    return {
        "value": value,
        "peer_count": int(len(peers)),
        "peer_median": float(peers.median()) if len(peers) else None,
        "peer_min": float(peers.min()) if len(peers) else None,
        "peer_max": float(peers.max()) if len(peers) else None,
        "percentile": percentile,
    }


def peer_valuation(repo: ReadRepository, ticker: str, max_peers: int = 25) -> dict[str, Any]:
    """Compare one company's latest valuation snapshot with the other companies
    in its sub-industry: per-metric value, peer median/min/max and percentile,
    plus a peer table with cluster labels."""
    info = resolve_company(repo, ticker)
    t = info["ticker"]
    sub_industry = info.get("sub_industry")
    if not sub_industry:
        raise ToolInputError(f"{t} has no sub_industry stored, so there is no peer group to compare against.")
    max_peers = clamp(max_peers, 1, MAX_PEERS)

    snapshot = _metric_frame(repo.recent_metrics_by_subindustry(sub_industry))
    notes = list(SNAPSHOT_NOTES)
    if sub_industry == "Misc.":
        notes.append(
            "sub_industry is 'Misc.' (the placeholder used when tickers are fetched with --tickers), so these "
            "'peers' are just every ticker fetched that way and are NOT a meaningful peer group."
        )
    if snapshot.empty or t not in set(snapshot["ticker"]):
        return to_jsonable({
            "ticker": t, "name": info["name"], "sub_industry": sub_industry,
            "metrics": None, "peers": [], "notes": notes + [f"No valuation snapshot is stored for {t}."],
        })

    own = snapshot[snapshot["ticker"] == t].iloc[0]
    others = snapshot[snapshot["ticker"] != t]
    metrics = {m: _metric_stats(own[m], others[m]) for m in METRICS if m in snapshot.columns}

    names = repo.fetch_dataframe(CompanyInfo, sub_industry=sub_industry)[["ticker", "name"]]
    clusters = _latest_clusters(repo)
    peers = others.merge(names, on="ticker", how="left").merge(clusters, on="ticker", how="left")
    peers = peers.sort_values("market_cap", ascending=False, na_position="last")
    shown = peers.head(max_peers)

    own_cluster = clusters[clusters["ticker"] == t]

    return to_jsonable({
        "ticker": t,
        "name": info["name"],
        "sector": info["sector"],
        "sub_industry": sub_industry,
        "peer_count": int(len(others)),
        "cluster": None if own_cluster.empty else {
            "label": own_cluster.iloc[0]["cluster"], "as_of": own_cluster.iloc[0]["cluster_as_of"],
        },
        "metrics": metrics,
        "peers": df_records(shown, PEER_COLUMNS),
        "peers_truncated": bool(len(peers) > max_peers),
        "notes": notes + [CLUSTER_MEANING],
    })


def valuation_clusters(
    repo: ReadRepository, ticker: str | None = None, sub_industry: str | None = None
) -> dict[str, Any]:
    """Latest stored valuation-cluster label for one ticker, or for every
    company in one sub-industry. Pass exactly one of the two."""
    if bool(ticker) == bool(sub_industry):
        raise ToolInputError("Pass exactly one of ticker or sub_industry.")

    companies = repo.fetch_dataframe(CompanyInfo)
    clusters = _latest_clusters(repo)

    if ticker:
        info = resolve_company(repo, ticker)
        row = clusters[clusters["ticker"] == info["ticker"]]
        return to_jsonable({
            "ticker": info["ticker"],
            "name": info["name"],
            "sub_industry": info.get("sub_industry"),
            "cluster": None if row.empty else row.iloc[0]["cluster"],
            "as_of": None if row.empty else row.iloc[0]["cluster_as_of"],
            "notes": [CLUSTER_MEANING] + ([] if not row.empty else ["No cluster label is stored for this ticker."]),
        })

    wanted = sub_industry.strip().casefold()
    known = sorted(companies["sub_industry"].dropna().unique())
    match = [s for s in known if s.casefold() == wanted]
    if not match:
        close = difflib.get_close_matches(sub_industry.strip(), known, n=5, cutoff=0.5)
        hint = f" Did you mean: {', '.join(close)}?" if close else " Use list_sectors to see valid names."
        raise ToolInputError(f"Unknown sub_industry {sub_industry!r}.{hint}")

    group = companies[companies["sub_industry"] == match[0]][["ticker", "name"]].merge(
        clusters, on="ticker", how="left"
    ).sort_values("ticker")
    members = int((group["cluster"] == "Cluster member").sum())
    return to_jsonable({
        "sub_industry": match[0],
        "company_count": int(len(group)),
        "cluster_members": members,
        "not_cluster_members": int((group["cluster"] == "Not cluster member").sum()),
        "unlabelled": int(group["cluster"].isna().sum()),
        "companies": df_records(group, ["ticker", "name", "cluster", "cluster_as_of"]),
        "notes": [CLUSTER_MEANING],
    })
