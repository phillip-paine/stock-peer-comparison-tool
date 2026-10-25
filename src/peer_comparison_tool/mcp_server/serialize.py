"""
Turn pandas / numpy / datetime values into plain JSON-safe Python.

This is the one place the output boundary is enforced, because the data layer's
known failure modes all surface here:

- NaN / NaT / pd.NA become `None` (never the string "nan" -- see the display
  gotcha in the project notes).
- `inf` / `-inf` become `None`. They really occur: the pipeline stores a
  trailing P/E of +inf for loss-making companies (`trailingPE == "Infinity"`),
  and JSON has no infinity.
- numpy scalars (`numpy.int64` etc.) become Python `int` / `float`; the json
  encoder rejects them.
- dates and timestamps become ISO `YYYY-MM-DD` strings. All series here are
  daily, so the time of day is dropped.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd


def to_jsonable(value: Any) -> Any:
    """Recursively convert `value` to something `json.dumps(allow_nan=False)` accepts."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, (pd.Series, pd.Index)):
        return [to_jsonable(v) for v in value.tolist()]

    # Scalars from here on. pd.isna handles NaN, NaT and pd.NA in one call.
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, Decimal):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, datetime):          # includes pd.Timestamp
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def df_records(df: pd.DataFrame, columns: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """DataFrame -> list of JSON-safe row dicts (optionally a column subset, in order)."""
    if df.empty:
        return []
    if columns is not None:
        df = df[[c for c in columns if c in df.columns]]
    return [to_jsonable(record) for record in df.to_dict("records")]


def truncate(rows: Iterable[Any], limit: int) -> tuple[list[Any], bool]:
    """First `limit` rows, and whether anything was cut."""
    rows = list(rows)
    return rows[:limit], len(rows) > limit


def clamp(value: int, low: int, high: int) -> int:
    """Pin an integer argument into [low, high] rather than erroring: a model
    asking for 10,000 rows should get the cap, not a failed call."""
    return max(low, min(high, int(value)))
