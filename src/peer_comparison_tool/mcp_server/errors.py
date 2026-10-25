"""Errors the tool functions raise for bad input (unknown ticker, bad argument).

Kept free of any `fastmcp` import so the tool modules stay framework-free;
`server.py` converts these to the MCP error type, whose message the model sees
and can act on -- so messages should say what to try instead.
"""
from __future__ import annotations


class ToolInputError(ValueError):
    """The caller passed something the tool can't act on. The message is shown
    to the model, so it should say how to fix the call."""
