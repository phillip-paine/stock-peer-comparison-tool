"""Tests for peer_comparison_tool.main's ticker/sub-industry filtering.
Pure function, no DB/network -- load_company_names() is monkeypatched to
avoid touching the real sp500_security_ticker.csv."""
from __future__ import annotations

import pandas as pd
import pytest

from peer_comparison_tool import main as main_module


@pytest.fixture(autouse=True)
def fake_company_names(monkeypatch):
    df = pd.DataFrame([
        {"Symbol": "MSFT", "Security": "Microsoft Corp.", "GICS Sector": "Information Technology",
         "GICS Sub-Industry": "Systems Software"},
        {"Symbol": "ORCL", "Security": "Oracle Corp.", "GICS Sector": "Information Technology",
         "GICS Sub-Industry": "Systems Software"},
        {"Symbol": "AAPL", "Security": "Apple Inc.", "GICS Sector": "Information Technology",
         "GICS Sub-Industry": "Technology Hardware, Storage & Peripherals"},
        {"Symbol": "JNJ", "Security": "Johnson & Johnson", "GICS Sector": "Health Care",
         "GICS Sub-Industry": "Pharmaceuticals"},
    ])
    monkeypatch.setattr(main_module, "load_company_names", lambda: df)
    return df


def test_gics_sub_industry_filters_narrower_than_sector():
    result = main_module.build_ticker_subindustry_map(gics_sub_industry="Systems Software")

    assert result == {"MSFT": "Systems Software", "ORCL": "Systems Software"}


def test_gics_sector_includes_every_sub_industry_within_it():
    result = main_module.build_ticker_subindustry_map(gics_sector="Information Technology")

    assert result == {
        "MSFT": "Systems Software",
        "ORCL": "Systems Software",
        "AAPL": "Technology Hardware, Storage & Peripherals",
    }


def test_gics_sub_industry_takes_priority_over_gics_sector_if_both_given():
    result = main_module.build_ticker_subindustry_map(
        gics_sector="Health Care", gics_sub_industry="Systems Software"
    )

    # Sub-industry filter wins -- "Systems Software" tickers, even though
    # they're in a different sector than the one also passed in.
    assert result == {"MSFT": "Systems Software", "ORCL": "Systems Software"}


def test_no_filters_returns_every_ticker():
    result = main_module.build_ticker_subindustry_map()

    assert set(result.keys()) == {"MSFT", "ORCL", "AAPL", "JNJ"}
