"""The registered MCP surface, driven through fastmcp's in-memory client.

Skipped when fastmcp isn't installed, so the tool tests still run without it.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest

pytest.importorskip("fastmcp")

from fastmcp import Client  # noqa: E402

from peer_comparison_tool.mcp_server.server import build_server  # noqa: E402

EXPECTED_TOOLS = {
    "data_freshness", "list_sectors", "list_companies", "company_profile",
    "price_history", "asset_moves",
    "quarterly_financials", "balance_sheet", "cash_flow",
    "peer_valuation", "valuation_clusters",
}


@pytest.fixture()
def server(repo):
    @contextmanager
    def provider():
        yield repo

    return build_server(provider)


def _run(coro):
    return asyncio.run(coro)


def test_exposes_exactly_the_expected_read_only_tools(server):
    async def go():
        async with Client(server) as client:
            return await client.list_tools()

    tools = _run(go())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.annotations is not None and tool.annotations.readOnlyHint is True, tool.name
        assert tool.description, f"{tool.name} needs a description the model can read"


def test_no_tool_accepts_free_form_sql(server):
    async def go():
        async with Client(server) as client:
            return await client.list_tools()

    for tool in _run(go()):
        params = set(tool.inputSchema.get("properties", {}))
        assert not params & {"sql", "query_sql", "statement"}, tool.name


def test_call_returns_structured_json(server):
    async def go():
        async with Client(server) as client:
            return await client.call_tool("price_history", {"ticker": "AAA", "observations": 3})

    result = _run(go())
    data = result.structured_content
    assert data["instrument"] == "AAA"
    assert [r["close"] for r in data["rows"]] == [137.0, 138.0, 139.0]


def test_bad_input_surfaces_as_an_error_with_a_retry_hint(server):
    async def go():
        async with Client(server) as client:
            return await client.call_tool("company_profile", {"ticker": "AAX"})

    with pytest.raises(Exception, match="Did you mean: AAA"):
        _run(go())
