"""The output boundary: everything a tool returns must survive json.dumps(allow_nan=False)."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd

from peer_comparison_tool.mcp_server.serialize import clamp, df_records, to_jsonable, truncate


def _roundtrips(value):
    return json.loads(json.dumps(to_jsonable(value), allow_nan=False))


def test_missing_values_become_null_not_the_string_nan():
    assert _roundtrips({"a": np.nan, "b": None, "c": pd.NA, "d": pd.NaT}) == {
        "a": None, "b": None, "c": None, "d": None,
    }


def test_infinity_becomes_null():
    # The pipeline stores +inf as the trailing P/E of loss-making companies.
    assert _roundtrips([float("inf"), -np.inf, np.float64("inf")]) == [None, None, None]


def test_numpy_scalars_become_python_numbers():
    out = to_jsonable({"i": np.int64(7), "f": np.float32(1.5), "b": np.bool_(True)})
    assert out == {"i": 7, "f": 1.5, "b": True}
    assert type(out["i"]) is int and type(out["b"]) is bool


def test_dates_and_timestamps_become_iso_dates():
    assert to_jsonable(date(2026, 10, 16)) == "2026-10-16"
    assert to_jsonable(pd.Timestamp("2026-10-16 15:30")) == "2026-10-16"
    assert to_jsonable(datetime(2026, 10, 16, 9, 0)) == "2026-10-16"


def test_decimal_and_nested_containers():
    assert _roundtrips({"x": [Decimal("1.25"), (np.int64(2), np.nan)]}) == {"x": [1.25, [2, None]]}


def test_df_records_selects_columns_in_order_and_cleans_values():
    df = pd.DataFrame({"d": [date(2026, 1, 2)], "v": [np.nan], "w": [np.int64(3)], "skip": ["x"]})
    assert df_records(df, ["w", "d", "v", "missing"]) == [{"w": 3, "d": "2026-01-02", "v": None}]
    assert df_records(pd.DataFrame()) == []


def test_truncate_and_clamp():
    assert truncate(range(5), 3) == ([0, 1, 2], True)
    assert truncate(range(2), 3) == ([0, 1], False)
    assert clamp(10_000, 1, 500) == 500
    assert clamp(-4, 1, 500) == 1
