"""
FastMCP server: registers the read-only tools from `tools/` over stdio.

`build_server()` takes the repository provider as an argument so tests can hand
it the in-memory fixture session; production uses `db.read_repository`, which
opens the SQLite file read-only.

Registration uses the call form `mcp.tool(...)(fn)` on plain functions rather than
decorating module-level functions, so the implementations stay ordinary callables
whichever fastmcp major version is installed.

IMPORTANT for stdio: stdout carries the protocol. Never print() in this package;
logging is configured to stderr in `main()`.
"""
from __future__ import annotations

import logging
import sys
from contextlib import AbstractContextManager
from typing import Any, Callable, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .db import check_database, read_repository
from .errors import ToolInputError
from .read_repository import ReadRepository
from .tools import fundamentals, prices, reference, valuation

logger = logging.getLogger(__name__)

SERVER_NAME = "peer-comparison-tool"

INSTRUCTIONS = """\
Curated, pipeline-maintained market data for US-listed stocks (S&P 500 universe) and a set of macro
assets. READ-ONLY: you can look data up, not change it, and there is no free-form SQL.

Start with data_freshness to see how current the data is, and list_sectors / list_companies to find
tickers. Peer comparisons are meaningful at sub-industry level (peer_valuation, valuation_clusters).
Every response carries 'notes' describing units and caveats -- read them: some conventions differ
between tools (e.g. quarterly margins are percent, valuation-snapshot margins are fractions).
Report the as_of / latest_date with any figure you quote, and do not extrapolate beyond the data.
"""

# Every tool is a pure read of local, already-stored data.
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

RepoProvider = Callable[[], AbstractContextManager[ReadRepository]]


def build_server(repo_provider: RepoProvider = read_repository) -> FastMCP:
    mcp = FastMCP(name=SERVER_NAME, instructions=INSTRUCTIONS)

    def run(fn: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        """One tool call = one short read-only session. Bad input becomes a
        ToolError whose message tells the model how to retry."""
        try:
            with repo_provider() as repo:
                return fn(repo, *args, **kwargs)
        except ToolInputError as exc:
            raise ToolError(str(exc)) from exc

    # ---- reference ----------------------------------------------------

    @mcp.tool(name="data_freshness", annotations=READ_ONLY)
    def data_freshness() -> dict[str, Any]:
        """Latest observation date, age in days and row count per dataset, plus the last
        pipeline fetch date. Call this first to judge how current the data is."""
        return run(reference.data_freshness)

    @mcp.tool(name="list_sectors", annotations=READ_ONLY)
    def list_sectors() -> dict[str, Any]:
        """Sectors and sub-industries in the database with company counts. Use the exact
        sub-industry names with list_companies and valuation_clusters."""
        return run(reference.list_sectors)

    @mcp.tool(name="list_companies", annotations=READ_ONLY)
    def list_companies(
        sector: str | None = None,
        sub_industry: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Find companies. sector / sub_industry: case-insensitive exact match. query: substring of
        ticker or company name. limit: max rows (capped at 500); 'truncated' says if more matched."""
        return run(reference.list_companies, sector=sector, sub_industry=sub_industry, query=query, limit=limit)

    @mcp.tool(name="company_profile", annotations=READ_ONLY)
    def company_profile(ticker: str) -> dict[str, Any]:
        """One-call overview of a company: identity, latest close, latest valuation snapshot
        (market cap, P/E, P/B, ROE, EV/EBITDA ...), valuation-cluster label and data coverage."""
        return run(reference.company_profile, ticker)

    # ---- prices -------------------------------------------------------

    @mcp.tool(name="price_history", annotations=READ_ONLY)
    def price_history(
        ticker: str,
        observations: int = prices.DEFAULT_OBSERVATIONS,
        frequency: Literal["daily", "weekly", "monthly"] = "daily",
    ) -> dict[str, Any]:
        """Close-price history for a stock ticker (e.g. AAPL) or a tracked asset by symbol or name
        (SPY, ^TNX, GC=F, US10Y_Yield ...). Returns the latest `observations` rows (max 750) at the
        chosen frequency, with first/last close, period return, high and low. Weekly/monthly rows
        use the last actual trading day of each period."""
        return run(prices.price_history, ticker, observations=observations, frequency=frequency)

    @mcp.tool(name="asset_moves", annotations=READ_ONLY)
    def asset_moves(asset_class: str | None = None) -> dict[str, Any]:
        """Latest level and 1-day / 1-week / 1-month change for every tracked non-stock asset
        (commodity, index_fund, etf, fx, rate). Optionally restrict to one asset_class."""
        return run(prices.asset_moves, asset_class=asset_class)

    # ---- fundamentals -------------------------------------------------

    @mcp.tool(name="quarterly_financials", annotations=READ_ONLY)
    def quarterly_financials(ticker: str, quarters: int = 8, include_yoy: bool = True) -> dict[str, Any]:
        """Reported quarters (oldest first): basic EPS, operating/net income, gross/operating/net/EBITDA
        margins (percent), with year-over-year changes when include_yoy. quarters max 40."""
        return run(fundamentals.quarterly_financials, ticker, quarters=quarters, include_yoy=include_yoy)

    @mcp.tool(name="balance_sheet", annotations=READ_ONLY)
    def balance_sheet(ticker: str, periods: int = 4) -> dict[str, Any]:
        """Annual balance-sheet metrics (oldest first). NOTE the notes field: quick_ratio and
        equity_ratio use pipeline-specific definitions that differ from the textbook ones."""
        return run(fundamentals.balance_sheet, ticker, periods=periods)

    @mcp.tool(name="cash_flow", annotations=READ_ONLY)
    def cash_flow(ticker: str, periods: int = 4) -> dict[str, Any]:
        """Free cash flow, operating cash flow and capex per period (oldest first)."""
        return run(fundamentals.cash_flow, ticker, periods=periods)

    # ---- valuation ----------------------------------------------------

    @mcp.tool(name="peer_valuation", annotations=READ_ONLY)
    def peer_valuation(ticker: str, max_peers: int = 25) -> dict[str, Any]:
        """Compare a company's latest valuation snapshot with the other companies in its sub-industry:
        per metric the company value, peer median/min/max and a 0-100 percentile (position, not a
        good/bad verdict), plus a peer table (largest by market cap first) with cluster labels."""
        return run(valuation.peer_valuation, ticker, max_peers=max_peers)

    @mcp.tool(name="valuation_clusters", annotations=READ_ONLY)
    def valuation_clusters(ticker: str | None = None, sub_industry: str | None = None) -> dict[str, Any]:
        """Latest stored DBSCAN valuation-cluster label: for one ticker, or for every company in one
        sub-industry. Pass exactly one of ticker / sub_industry. Read the notes for what the labels mean."""
        return run(valuation.valuation_clusters, ticker=ticker, sub_industry=sub_industry)

    return mcp


def main() -> None:
    """Entry point: stdio transport, logs to stderr."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    path = check_database()      # clear failure at startup if the DB is missing / not SQLite
    logger.info("Serving %s (read-only) over stdio", path)
    build_server().run()


if __name__ == "__main__":
    main()
