"""Tool implementations: plain functions `(repo, **args) -> JSON-safe dict`.

No MCP/fastmcp imports here -- `server.py` registers these. That keeps them
testable against the in-memory `session` fixture like the rest of the data layer.
"""
