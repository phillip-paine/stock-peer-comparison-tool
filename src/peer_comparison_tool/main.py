"""
CLI entry point for the data pipeline.

Replaces the root `main.py`. The original `main_run()` mixed data-pipeline
orchestration with starting the Dash server in the same function, and its
`execute_app()` click command was marked "TODO out of date - will not run
from CLI currently" — its call signature didn't match the real
`create_ticker_data()` function it was meant to invoke.

This version covers only the data-layer scope of this refactor: fetch,
transform, persist, aggregate. It deliberately does not start the
dashboard — that's a separate piece of work. See the note at the bottom of
this file for what needs to happen before the two are wired back together.
"""
from __future__ import annotations

import logging

import click

from peer_comparison_tool.data.config import settings
from peer_comparison_tool.data.constants import TICKERS
from peer_comparison_tool.data.database import init_db, session_scope
from peer_comparison_tool.data.pipeline import load_company_names, run_pipeline
from peer_comparison_tool.data.repository import Repository

logger = logging.getLogger(__name__)


def build_ticker_subindustry_map(
        gics_sector: str | None = None, gics_sub_industry: str | None = None
) -> dict[str, str]:
    """Ticker -> GICS sub-industry, sourced from the cached S&P 500
    constituent list. Optionally filtered to one GICS sector, or narrower
    still to one GICS sub-industry — the level comparisons/clustering
    actually operate at, since a whole sector (e.g. "Information
    Technology") spans wildly different businesses (software, hardware,
    semiconductors, IT services, ...) that aren't meaningfully comparable
    to each other. The original controlled this by commenting/uncommenting
    lines at the bottom of main.py; here they're runtime parameters instead.
    """
    df = load_company_names()
    if gics_sub_industry:
        df = df[df["GICS Sub-Industry"] == gics_sub_industry]
    elif gics_sector:
        df = df[df["GICS Sector"] == gics_sector]
    return dict(zip(df["Symbol"], df["GICS Sub-Industry"]))


@click.command()
@click.option(
    "--tickers", default=None,
    help="Comma-separated stock tickers to fetch, e.g. 'AAPL,MSFT'. "
         "Defaults to the built-in TICKERS list if omitted.",
)
@click.option(
    "--gics-sub-industry", default=None,
    help="Restrict to one GICS sub-industry from the S&P 500 constituent list, "
         "e.g. 'Systems Software'. This is the level comparisons/clustering are "
         "actually meaningful at. Ignored if --tickers is given; takes priority "
         "over --gics-sector if both are given.",
)
@click.option(
    "--gics-sector", default=None,
    help="Restrict to one GICS sector (broader than sub-industry -- spans many "
         "different kinds of business) from the S&P 500 constituent list, "
         "e.g. 'Health Care'. Ignored if --tickers or --gics-sub-industry is given.",
)
def run(tickers: str | None, gics_sub_industry: str | None, gics_sector: str | None) -> None:
    """Fetch, transform, and persist stock/asset-class data, then refresh
    the materialized aggregate tables."""
    logging.basicConfig(level=logging.INFO)

    if tickers:
        ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
        ticker_subindustry_map = {t: "Misc." for t in ticker_list}
    elif gics_sub_industry or gics_sector:
        ticker_subindustry_map = build_ticker_subindustry_map(gics_sector, gics_sub_industry)
    else:
        ticker_subindustry_map = {t: "Misc." for t in TICKERS}

    init_db()
    with session_scope() as session:
        repo = Repository(session)
        run_pipeline(repo, ticker_subindustry_map)

    logger.info("Pipeline complete. Data written to %s", settings.database_url)


if __name__ == "__main__":
    run()


# --- Note on reconnecting the dashboard ---
# The dashboard (src/peer_comparison_tool/comparison_tool/) reads its own
# DB_PATH from comparison_tool/constants.py, separate from this refactor's
# settings.database_url in data/config.py. Until the dashboard is refactored,
# point PCT_DATABASE_URL (or comparison_tool's DB_PATH) at the same file so
# both sides agree on where the data actually lives.
