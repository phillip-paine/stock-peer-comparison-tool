from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from peer_comparison_tool.data.clients.yfinance_client import DataRetrievalError
from peer_comparison_tool.data.models import (
    AssetClassTimeSeries,
    BalanceSheetData,
    CompanyInfo,
    QuarterlyFinancialData,
    TickerMostRecentMetric,
    TickerTimeSeries,
)
from peer_comparison_tool.data.pipeline import (
    ingest_asset_classes,
    ingest_ticker,
    ingest_tickers,
    run_pipeline,
)
from peer_comparison_tool.data.repository import Repository


def _quarterly_raw() -> pd.DataFrame:
    rows = {
        "Basic EPS": [1.5, 1.2],
        "Operating Income": [500.0, 400.0],
        "Total Revenue": [2000.0, 1800.0],
        "Gross Profit": [800.0, 700.0],
        "Net Income": [300.0, 250.0],
        "EBITDA": [600.0, 500.0],
    }
    return pd.DataFrame.from_dict(rows, orient="index", columns=pd.to_datetime(["2026-03-31", "2025-12-31"]))


def _balance_sheet_raw() -> pd.DataFrame:
    rows = {
        "OrdinarySharesNumber": [1000.0],
        "StockholdersEquity": [5000.0],
        "TotalLiabilitiesNetMinorityInterest": [3000.0],
        "CurrentAssets": [4000.0],
    }
    return pd.DataFrame.from_dict(rows, orient="index", columns=pd.to_datetime(["2026-01-01"]))


def _price_history_raw() -> pd.DataFrame:
    return pd.DataFrame(
        {"Close": [150.0, 155.0]},
        index=pd.date_range("2026-01-01", periods=2, freq="D", tz="America/New_York", name="Date"),
    )


def _cashflow_raw() -> pd.DataFrame:
    rows = {"Free Cash Flow": [100.0], "Operating Cash Flow": [150.0], "Capital Expenditure": [-50.0]}
    return pd.DataFrame.from_dict(rows, orient="index", columns=pd.to_datetime(["2026-01-01"]))


def _multi_asset_raw(symbols: list[str]) -> pd.DataFrame:
    idx = pd.to_datetime(["2026-01-01", "2026-01-02"])
    close_df = pd.DataFrame({s: [100.0, 101.0] for s in symbols}, index=idx)
    volume_df = pd.DataFrame({s: [1000, 1000] for s in symbols}, index=idx)
    return pd.concat({"Close": close_df, "Volume": volume_df}, axis=1)


class FakeYFinanceClient:
    """Test double implementing the same interface as YFinanceClient, with
    per-ticker canned responses and the ability to simulate failures."""

    def __init__(self, tickers: dict[str, dict] | None = None, multi_asset: pd.DataFrame | None = None,
                 raise_on: set[tuple[str, str]] = frozenset()):
        self._tickers = tickers or {}
        self._multi_asset = multi_asset
        self._raise_on = raise_on
        self.calls: list[tuple[str, str]] = []

    def _maybe_raise(self, ticker: str, method: str):
        self.calls.append((ticker, method))
        if (ticker, method) in self._raise_on:
            raise DataRetrievalError(f"{method} failed for {ticker}")

    def fetch_info(self, ticker):
        self._maybe_raise(ticker, "info")
        return self._tickers[ticker]["info"]

    def fetch_quarterly_financials(self, ticker):
        self._maybe_raise(ticker, "quarterly")
        return self._tickers[ticker]["quarterly"]

    def fetch_balance_sheet(self, ticker):
        self._maybe_raise(ticker, "balance_sheet")
        return self._tickers[ticker]["balance_sheet"]

    def fetch_cashflow(self, ticker):
        self._maybe_raise(ticker, "cashflow")
        return self._tickers[ticker].get("cashflow", pd.DataFrame())

    def fetch_price_history(self, ticker, period="2y"):
        self._maybe_raise(ticker, "price_history")
        return self._tickers[ticker].get("price_history", pd.DataFrame())

    def fetch_multi_asset_history(self, symbols, period="2y", interval="1d"):
        self.calls.append(("_assets", "multi_asset"))
        if self._multi_asset is None:
            raise DataRetrievalError("no multi-asset fixture configured")
        return self._multi_asset


def _valid_aapl_fixture() -> dict:
    return {
        "info": {"sector": "Technology", "industry": "Hardware", "trailingPE": 28.0},
        "quarterly": _quarterly_raw(),
        "balance_sheet": _balance_sheet_raw(),
        "cashflow": _cashflow_raw(),
        "price_history": _price_history_raw(),
    }


COMPANY_NAMES = pd.DataFrame({"Symbol": ["AAPL"], "Security": ["Apple Inc."]})


class TestIngestTicker:
    def test_happy_path_writes_all_tables(self, session):
        client = FakeYFinanceClient(tickers={"AAPL": _valid_aapl_fixture()})
        repo = Repository(session)

        result = ingest_ticker(client, repo, "AAPL", "Tech Hardware", COMPANY_NAMES)
        session.commit()

        assert result is True
        assert len(repo.fetch_dataframe(CompanyInfo)) == 1
        assert repo.fetch_dataframe(CompanyInfo).iloc[0]["name"] == "Apple Inc."
        assert len(repo.fetch_dataframe(TickerMostRecentMetric)) == 1
        assert len(repo.fetch_dataframe(TickerTimeSeries)) == 2
        assert len(repo.fetch_dataframe(QuarterlyFinancialData)) == 2
        assert len(repo.fetch_dataframe(BalanceSheetData)) == 1

    def test_falls_back_to_ticker_symbol_when_name_not_found(self, session):
        client = FakeYFinanceClient(tickers={"ZZZZ": _valid_aapl_fixture()})
        repo = Repository(session)
        ingest_ticker(client, repo, "ZZZZ", "Tech Hardware", COMPANY_NAMES)
        session.commit()
        assert repo.fetch_dataframe(CompanyInfo).iloc[0]["name"] == "ZZZZ"

    def test_empty_balance_sheet_skips_ticker(self, session):
        fixture = _valid_aapl_fixture()
        fixture["balance_sheet"] = pd.DataFrame()
        client = FakeYFinanceClient(tickers={"AAPL": fixture})
        repo = Repository(session)

        result = ingest_ticker(client, repo, "AAPL", "Tech Hardware", COMPANY_NAMES)
        session.commit()

        assert result is False
        assert repo.fetch_dataframe(CompanyInfo).empty

    def test_empty_quarterly_financials_skips_ticker(self, session):
        fixture = _valid_aapl_fixture()
        fixture["quarterly"] = pd.DataFrame()
        client = FakeYFinanceClient(tickers={"AAPL": fixture})
        repo = Repository(session)

        result = ingest_ticker(client, repo, "AAPL", "Tech Hardware", COMPANY_NAMES)
        assert result is False

    def test_balance_sheet_fetch_error_skips_ticker_gracefully(self, session):
        client = FakeYFinanceClient(
            tickers={"AAPL": _valid_aapl_fixture()},
            raise_on={("AAPL", "balance_sheet")},
        )
        repo = Repository(session)
        result = ingest_ticker(client, repo, "AAPL", "Tech Hardware", COMPANY_NAMES)
        assert result is False

    def test_missing_sector_skips_ticker(self, session):
        fixture = _valid_aapl_fixture()
        fixture["info"] = {"industry": "Hardware"}  # no 'sector'
        client = FakeYFinanceClient(tickers={"AAPL": fixture})
        repo = Repository(session)

        result = ingest_ticker(client, repo, "AAPL", "Tech Hardware", COMPANY_NAMES)
        session.commit()

        assert result is False
        assert repo.fetch_dataframe(CompanyInfo).empty

    def test_cashflow_fetch_error_does_not_abort_ticker(self, session):
        client = FakeYFinanceClient(
            tickers={"AAPL": _valid_aapl_fixture()},
            raise_on={("AAPL", "cashflow")},
        )
        repo = Repository(session)

        result = ingest_ticker(client, repo, "AAPL", "Tech Hardware", COMPANY_NAMES)
        session.commit()

        assert result is True
        assert len(repo.fetch_dataframe(CompanyInfo)) == 1

    def test_price_history_fetch_error_does_not_abort_ticker(self, session):
        client = FakeYFinanceClient(
            tickers={"AAPL": _valid_aapl_fixture()},
            raise_on={("AAPL", "price_history")},
        )
        repo = Repository(session)

        result = ingest_ticker(client, repo, "AAPL", "Tech Hardware", COMPANY_NAMES)
        session.commit()

        assert result is True
        assert repo.fetch_dataframe(TickerTimeSeries).empty


class TestIngestTickers:
    def test_skips_tickers_with_recent_data(self, session):
        repo = Repository(session)
        repo.record_fetch(["AAPL"], as_of=date.today())
        session.commit()

        client = FakeYFinanceClient(tickers={"AAPL": _valid_aapl_fixture(), "MSFT": _valid_aapl_fixture()})
        fetched = ingest_tickers(
            client, repo, {"AAPL": "Tech Hardware", "MSFT": "Tech Hardware"}, company_names=COMPANY_NAMES,
        )
        session.commit()

        assert fetched == ["MSFT"]
        assert ("AAPL", "balance_sheet") not in client.calls

    def test_refetches_stale_tickers(self, session):
        repo = Repository(session)
        repo.record_fetch(["AAPL"], as_of=date.today() - timedelta(days=30))
        session.commit()

        client = FakeYFinanceClient(tickers={"AAPL": _valid_aapl_fixture()})
        fetched = ingest_tickers(client, repo, {"AAPL": "Tech Hardware"}, company_names=COMPANY_NAMES)

        assert fetched == ["AAPL"]

    def test_failed_tickers_are_not_recorded_as_fetched(self, session):
        repo = Repository(session)
        client = FakeYFinanceClient(tickers={"AAPL": {**_valid_aapl_fixture(), "balance_sheet": pd.DataFrame()}})

        fetched = ingest_tickers(client, repo, {"AAPL": "Tech Hardware"}, company_names=COMPANY_NAMES)
        session.commit()

        assert fetched == []
        assert repo.is_data_recent("AAPL", max_age_days=14) is False


class TestIngestAssetClasses:
    def test_fetches_only_stale_symbols(self, session):
        from peer_comparison_tool.data.constants import asset_symbols

        repo = Repository(session)
        all_symbols = asset_symbols()
        already_recent = all_symbols[0]
        repo.record_fetch([already_recent], as_of=date.today())
        session.commit()

        client = FakeYFinanceClient(multi_asset=_multi_asset_raw(all_symbols))
        fetched = ingest_asset_classes(client, repo, max_age_days=1)
        session.commit()

        assert already_recent not in fetched
        assert len(fetched) == len(all_symbols) - 1

    def test_all_recent_skips_the_fetch_entirely(self, session):
        from peer_comparison_tool.data.constants import asset_symbols

        repo = Repository(session)
        repo.record_fetch(asset_symbols(), as_of=date.today())
        session.commit()

        client = FakeYFinanceClient(multi_asset=None)  # would raise if called
        fetched = ingest_asset_classes(client, repo, max_age_days=1)

        assert fetched == []
        assert ("_assets", "multi_asset") not in client.calls

    def test_writes_asset_class_time_series(self, session):
        from peer_comparison_tool.data.constants import asset_symbols

        repo = Repository(session)
        client = FakeYFinanceClient(multi_asset=_multi_asset_raw(asset_symbols()))
        ingest_asset_classes(client, repo, max_age_days=1)
        session.commit()

        assert not repo.fetch_dataframe(AssetClassTimeSeries).empty

    def test_fetch_error_returns_empty_list_gracefully(self, session):
        repo = Repository(session)
        client = FakeYFinanceClient(multi_asset=None)
        fetched = ingest_asset_classes(client, repo, max_age_days=1)
        assert fetched == []


class TestRunPipeline:
    def test_end_to_end_populates_ticker_and_aggregate_tables(self, session):
        from peer_comparison_tool.data.constants import asset_symbols

        repo = Repository(session)
        client = FakeYFinanceClient(
            tickers={"AAPL": _valid_aapl_fixture()},
            multi_asset=_multi_asset_raw(asset_symbols()),
        )

        # bypass the CSV lookup for this integration test
        import peer_comparison_tool.data.pipeline as pipeline_module
        original_loader = pipeline_module.load_company_names
        pipeline_module.load_company_names = lambda: COMPANY_NAMES
        try:
            run_pipeline(repo, {"AAPL": "Tech Hardware"}, client=client)
            session.commit()
        finally:
            pipeline_module.load_company_names = original_loader

        assert not repo.fetch_dataframe(CompanyInfo).empty
        assert not repo.fetch_dataframe(AssetClassTimeSeries).empty
        assert repo.is_data_recent("AAPL", max_age_days=14) is True
