"""
MCP server exposing the curated data layer to an AI model.

Deliberately narrow: a fixed set of read-only tools, each wrapping specific
`Repository` reads and the existing pure transforms. There is no generic SQL
tool, and nothing here imports the pipeline or yfinance -- the server can only
read what the pipeline has already stored.

Importing this package does not import `fastmcp`; only `server` does, so the
tool functions in `tools/` can be tested without it.

Run (stdio):  python -m peer_comparison_tool.mcp_server
"""
