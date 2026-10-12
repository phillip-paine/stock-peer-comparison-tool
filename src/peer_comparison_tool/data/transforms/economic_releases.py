"""
FRED economic series -- catalog and pure, DB-free transforms.

Feeds the Market Conditions page's four FRED-backed sections: Rates & Curve,
Rate Expectations, Labor Market and Inflation. Each series arrives from
`FredClient.fetch_series_observations` as its own long, two-column
(date, value) frame, is persisted as-is in `EconomicReleaseData` by
`pipeline.ingest_economic_releases`, and is summarized here at display time.

Why a catalog instead of a bare id -> name dict
-----------------------------------------------
The first version treated every series the same: latest value, prior value,
and *percent change of the level*. That is wrong for most of what a macro
page shows -- unemployment moving 4.1 -> 4.2 is +0.1 percentage points (not
"+2.4%"), a payrolls print is jobs added (not a percent of 159 million), a
yield move is basis points, and CPI is read as month-on-month and
year-on-year inflation. `SeriesSpec` records, per series, how its level is
displayed and how its change is measured, so the summary and the formatting
can't drift apart.

FOMC projections are deliberately NOT summarized as "latest vs prior": the
latest observation of `FEDTARMD` is the furthest-out year, which makes a
"change" between consecutive observations meaningless. They get their own
shape (`build_sep_table`).

Market-implied rate expectations are NOT available from FRED (the usual
source is CME FedWatch, which has no free official API). `build_market_proxies`
reads the 3-month bill and 2-year yields against the effective fed funds rate
as honest *proxies* for the market leaning toward cuts or hikes. They are not
probabilities, and term premium / bill supply move them too -- the page says
so.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from .time_series import compute_yoy_by_date

# Observations to pull per series, by release frequency: ~2 years of history
# for daily series (charts), enough for a year-on-year plus slack for monthly.
HISTORY_LIMIT_BY_FREQUENCY = {"daily": 520, "weekly": 110, "monthly": 40, "annual": 30}
DEFAULT_HISTORY_LIMIT = 24  # series outside the catalog

# How a level is displayed.
#   percent    4.25 -> "4.25%"          spread_bp  0.45 -> "+45 bp" (FRED gives spreads in pp)
#   thousands  159540 -> "159.54M"      persons    231000 -> "231k"
#   index      321.64 -> "321.6"        dollars    36.12 -> "$36.12"
LEVEL_KINDS = {"percent", "spread_bp", "thousands", "persons", "index", "dollars"}
# How a change is measured.
#   bp   (latest - prior) * 100, series is in percent    pp   latest - prior, in percentage points
#   abs  latest - prior, in the series' own units         pct  (latest - prior) / |prior|
CHANGE_MODES = {"bp", "pp", "abs", "pct"}

CATEGORY_LABELS = {
    "rates": "Rates & Curve",
    "expectations": "Rate Expectations",
    "labor": "Labor Market",
    "inflation": "Inflation",
}


@dataclass(frozen=True)
class SeriesSpec:
    series_id: str
    name: str
    category: str
    frequency: str
    level_kind: str
    change_mode: str
    show_yoy: bool = False
    # False for series with no meaningful "latest vs prior" (FOMC projections).
    summarize: bool = True

    @property
    def history_limit(self) -> int:
        return HISTORY_LIMIT_BY_FREQUENCY[self.frequency]


_CATALOG_LIST = [
    # -- Rates & curve (daily, in percent) ----------------------------------------
    SeriesSpec("DGS10", "10Y Treasury Yield", "rates", "daily", "percent", "bp"),
    SeriesSpec("DGS2", "2Y Treasury Yield", "rates", "daily", "percent", "bp"),
    SeriesSpec("DGS3MO", "3M Treasury Yield", "rates", "daily", "percent", "bp"),
    SeriesSpec("T10Y2Y", "10Y-2Y Spread (2s10s)", "rates", "daily", "spread_bp", "bp"),
    SeriesSpec("DFF", "Effective Fed Funds Rate", "rates", "daily", "percent", "bp"),
    SeriesSpec("DFEDTARU", "Fed Funds Target (Upper)", "rates", "daily", "percent", "bp"),
    SeriesSpec("DFEDTARL", "Fed Funds Target (Lower)", "rates", "daily", "percent", "bp"),
    # -- FOMC Summary of Economic Projections (annual; year-end median of the rate midpoint)
    SeriesSpec("FEDTARMD", "FOMC Median Projection (Fed Funds)", "expectations", "annual",
               "percent", "bp", summarize=False),
    SeriesSpec("FEDTARMDLR", "FOMC Longer-Run Projection (Fed Funds)", "expectations", "annual",
               "percent", "bp", summarize=False),
    # -- Labor ----------------------------------------------------------------------
    SeriesSpec("PAYEMS", "Nonfarm Payrolls", "labor", "monthly", "thousands", "abs"),
    SeriesSpec("UNRATE", "Unemployment Rate", "labor", "monthly", "percent", "pp"),
    SeriesSpec("JTSJOL", "JOLTS Job Openings", "labor", "monthly", "thousands", "abs"),
    SeriesSpec("ICSA", "Initial Jobless Claims", "labor", "weekly", "persons", "abs"),
    SeriesSpec("CES0500000003", "Avg Hourly Earnings (Private)", "labor", "monthly",
               "dollars", "pct", show_yoy=True),
    # -- Inflation (price indices: month-on-month change and year-on-year) ----------
    SeriesSpec("CPIAUCSL", "CPI (All Items)", "inflation", "monthly", "index", "pct", show_yoy=True),
    SeriesSpec("CPILFESL", "Core CPI (ex Food & Energy)", "inflation", "monthly", "index", "pct", show_yoy=True),
    SeriesSpec("PCEPILFE", "Core PCE Price Index", "inflation", "monthly", "index", "pct", show_yoy=True),
]
SERIES_CATALOG: dict[str, SeriesSpec] = {spec.series_id: spec for spec in _CATALOG_LIST}

# id -> display name; for callers that only need the list of series to fetch.
FRED_SERIES = {sid: spec.name for sid, spec in SERIES_CATALOG.items()}

_CATALOG_ORDER = {sid: i for i, sid in enumerate(SERIES_CATALOG)}


def spec_for(series_id: str) -> SeriesSpec:
    """Catalog entry for `series_id`; a series outside the catalog still
    renders, as percent change of its level (what the original did for all)."""
    return SERIES_CATALOG.get(series_id) or SeriesSpec(series_id, series_id, "other", "monthly", "index", "pct")


# ---------------------------------------------------------------------------
# Latest vs prior
# ---------------------------------------------------------------------------

def _is_missing(value: Any) -> bool:
    return value is None or bool(pd.isna(value))


def _clean(observations: pd.DataFrame | None) -> pd.DataFrame:
    """Observations sorted oldest-first with NaN values dropped."""
    if observations is None or observations.empty:
        return pd.DataFrame(columns=["date", "value"])
    return observations.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)


def _latest_yoy(observations: pd.DataFrame) -> float | None:
    """Year-on-year change of the latest observation vs the observation on the
    exact same calendar date one year earlier (`compute_yoy_by_date`, the same
    matching the daily price series use; first-of-month FRED dates line up
    exactly). `None` if that exact prior date isn't in the data: no
    approximate matching, so a gap never silently becomes a YoY against a
    different month."""
    yoy = compute_yoy_by_date(observations.assign(_s="x"), ["_s"], "date", ["value"])
    if yoy.empty:
        return None
    last = yoy.sort_values("date").iloc[-1]
    if pd.Timestamp(last["date"]) != pd.Timestamp(observations["date"].iloc[-1]):
        return None
    value = last["value_yoy"]
    # `compute_yoy_by_date` returns percent (x100); every other change in this
    # module is a fraction, so convert at the boundary. (It also returns 0.0
    # rather than NaN for a zero year-ago value; the YoY series here are price
    # indices and dollar earnings, never zero.)
    return None if pd.isna(value) else float(value) / 100


def _change(mode: str, latest: float, prior: float) -> float | None:
    if mode == "bp":
        return (latest - prior) * 100
    if mode in ("pp", "abs"):
        return latest - prior
    if mode == "pct":
        return None if prior == 0 else (latest - prior) / abs(prior)
    raise ValueError(f"unknown change mode {mode!r}")


def latest_vs_prior_release(observations: pd.DataFrame, series_id: str) -> dict[str, Any] | None:
    """One series' latest-vs-prior comparison, in the units its catalog entry
    specifies (see `CHANGE_MODES`), plus a year-on-year change for series that
    ask for it. `None` if there's no data at all.

    A series with a single observation still returns a row (no prior, no
    change), consistent with `report_comparison.build_comparison_table`.
    """
    spec = spec_for(series_id)
    obs = _clean(observations)
    if obs.empty:
        return None

    latest = obs.iloc[-1]
    prior = obs.iloc[-2] if len(obs) > 1 else None
    latest_value = float(latest["value"])
    prior_value = float(prior["value"]) if prior is not None else None

    return {
        "series_id": series_id,
        "name": spec.name,
        "category": spec.category,
        "latest_date": latest["date"],
        "latest_value": latest_value,
        "prior_date": prior["date"] if prior is not None else None,
        "prior_value": prior_value,
        "change": _change(spec.change_mode, latest_value, prior_value) if prior_value is not None else None,
        "yoy": _latest_yoy(obs) if spec.show_yoy else None,
    }


def build_release_summary(
    observations_by_series: dict[str, pd.DataFrame], category: str | None = None
) -> list[dict[str, Any]]:
    """`latest_vs_prior_release` for each series, in catalog order (not
    alphabetical), optionally for one `category`. Series with no data are
    dropped rather than raising. FOMC projections are never included."""
    rows = []
    for series_id, observations in observations_by_series.items():
        spec = spec_for(series_id)
        if not spec.summarize or (category is not None and spec.category != category):
            continue
        row = latest_vs_prior_release(observations, series_id)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: _CATALOG_ORDER.get(r["series_id"], len(_CATALOG_ORDER)))
    return rows


# ---------------------------------------------------------------------------
# Formatting (strings for display; raw numbers stay in the summary rows)
# ---------------------------------------------------------------------------

def format_level(spec: SeriesSpec, value: Any) -> str:
    if _is_missing(value):
        return "n/a"
    kind = spec.level_kind
    if kind == "percent":
        return f"{value:.2f}%"
    if kind == "spread_bp":
        return f"{value * 100:+.0f} bp"
    if kind == "thousands":
        return f"{value / 1000:,.2f}M"
    if kind == "persons":
        return f"{value / 1000:,.0f}k"
    if kind == "dollars":
        return f"${value:,.2f}"
    return f"{value:,.1f}"  # index


def format_change(spec: SeriesSpec, value: Any) -> str:
    if _is_missing(value):
        return "n/a"
    mode = spec.change_mode
    if mode == "bp":
        return f"{value:+.0f} bp"
    if mode == "pp":
        return f"{value:+.1f} pp"
    if mode == "pct":
        return f"{value * 100:+.1f}%"
    if spec.level_kind == "thousands":  # abs, in thousands of persons
        return f"{value:+,.0f}k"
    if spec.level_kind == "persons":
        return f"{value / 1000:+,.0f}k"
    return f"{value:+,.2f}"


def format_yoy(value: Any) -> str:
    return "n/a" if _is_missing(value) else f"{value * 100:+.1f}%"


# ---------------------------------------------------------------------------
# Rate expectations
# ---------------------------------------------------------------------------

def _latest_value(observations: pd.DataFrame | None) -> float | None:
    obs = _clean(observations)
    return None if obs.empty else float(obs["value"].iloc[-1])


def current_policy_rate(observations_by_series: dict[str, pd.DataFrame]) -> tuple[float, str] | None:
    """The current policy rate to compare FOMC projections against, with a
    label for what it is. Prefers the target-range midpoint -- the FOMC
    projects "the midpoint of the appropriate target range", so that's the
    like-for-like comparison; the effective rate sits a few bp inside the
    range -- falling back to the effective rate."""
    upper = _latest_value(observations_by_series.get("DFEDTARU"))
    lower = _latest_value(observations_by_series.get("DFEDTARL"))
    if upper is not None and lower is not None:
        return (upper + lower) / 2, "target-range midpoint"
    effective = _latest_value(observations_by_series.get("DFF"))
    if effective is not None:
        return effective, "effective fed funds rate"
    return None


def build_sep_table(
    projections: pd.DataFrame | None,
    longer_run: pd.DataFrame | None,
    policy_rate: float | None,
    as_of: date,
) -> list[dict[str, Any]]:
    """FOMC median projected fed funds rate by year-end, current year onward,
    with the implied move from `policy_rate` in basis points, plus the
    longer-run projection. FRED dates each annual observation at the start of
    its year; years before `as_of`'s year are realized, not projections, and
    are dropped.

    FRED holds only the latest vintage, so this shows where the FOMC median
    sits now, not how it moved since the previous SEP.
    """
    rows: list[dict[str, Any]] = []

    def _gap(value: float) -> float | None:
        return None if policy_rate is None else (value - policy_rate) * 100

    proj = _clean(projections)
    if not proj.empty:
        proj = proj.assign(year=pd.to_datetime(proj["date"]).dt.year)
        for _, r in proj[proj["year"] >= as_of.year].sort_values("year").iterrows():
            rows.append({"label": f"{int(r['year'])} year-end", "year": int(r["year"]),
                         "median": float(r["value"]), "vs_current_bp": _gap(float(r["value"]))})

    lr_value = _latest_value(longer_run)
    if lr_value is not None:
        rows.append({"label": "Longer run", "year": None, "median": lr_value, "vs_current_bp": _gap(lr_value)})
    return rows


# Gaps inside this band read as "roughly in line". A judgement call, not a
# statistical threshold: Treasury yields (bond-equivalent basis) and the
# effective fed funds rate (money-market basis) differ by a few bp even when
# the market expects no change.
NOISE_BAND_BP = 10

PROXY_SERIES = [
    ("DGS3MO", "3M Treasury bill vs fed funds"),
    ("DGS2", "2Y Treasury vs fed funds"),
]


def build_market_proxies(observations_by_series: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Market-leaning proxies: how far the 3-month bill and 2-year Treasury
    yields sit from the effective fed funds rate, on the latest date both have
    data (they can lag by a day; mixing dates would pair a stale yield with a
    fresh policy rate). A yield below fed funds is consistent with the market
    pricing cuts, above with hikes. Proxies, NOT market-implied probabilities.
    """
    funds = _clean(observations_by_series.get("DFF"))
    if funds.empty:
        return []
    funds = funds.assign(date=pd.to_datetime(funds["date"])).rename(columns={"value": "policy_rate"})

    rows = []
    for series_id, name in PROXY_SERIES:
        yields = _clean(observations_by_series.get(series_id))
        if yields.empty:
            continue
        yields = yields.assign(date=pd.to_datetime(yields["date"])).rename(columns={"value": "yield_"})
        merged = pd.merge(yields, funds, on="date", how="inner").sort_values("date")
        if merged.empty:
            continue
        last = merged.iloc[-1]
        gap_bp = (float(last["yield_"]) - float(last["policy_rate"])) * 100
        if abs(gap_bp) <= NOISE_BAND_BP:
            reading = "roughly in line"
        else:
            reading = "hikes priced in" if gap_bp > 0 else "cuts priced in"
        rows.append({
            "name": name,
            "yield_": float(last["yield_"]),
            "policy_rate": float(last["policy_rate"]),
            "gap_bp": gap_bp,
            "reading": reading,
            "as_of": last["date"].date(),
        })
    return rows
