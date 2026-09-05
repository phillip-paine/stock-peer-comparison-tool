"""
Central configuration for the data layer.

Nothing in this module hits the network or the filesystem at import time.
All paths are resolved relative to the project (or overridden via env vars),
so the app runs on any machine without editing source — unlike the original
`~/Documents/Code/peer-comparison-tool/data/...` hardcoded paths.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Project root = three levels up from this file (data/ -> peer_comparison_tool/ -> src/ -> root)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _env_path(var_name: str, default: Path) -> Path:
    raw = os.getenv(var_name)
    return Path(raw).expanduser() if raw else default


def _env_int(var_name: str, default: int) -> int:
    raw = os.getenv(var_name)
    return int(raw) if raw else default


def _env_float(var_name: str, default: float) -> float:
    raw = os.getenv(var_name)
    return float(raw) if raw else default


@dataclass(frozen=True)
class DataConfig:
    """Immutable settings for data retrieval and storage.

    Every field can be overridden by an environment variable of the same
    name (upper-cased), so this works the same in local dev, CI, and prod
    without code changes.
    """

    # Where reference/downloaded CSVs live (e.g. sp500_security_ticker.csv)
    data_dir: Path = field(
        default_factory=lambda: _env_path("PCT_DATA_DIR", PROJECT_ROOT / "data_files")
    )

    # SQLAlchemy connection URL. Defaults to a local sqlite file under data_dir,
    # but can point anywhere (e.g. postgresql://...) without touching code.
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "PCT_DATABASE_URL",
            f"sqlite:///{(_env_path('PCT_DATA_DIR', PROJECT_ROOT / 'data_files') / 'comparison_tool.db')}",
        )
    )

    # Default ticker universe used when the caller doesn't supply one.
    default_tickers: tuple[str, ...] = ("AAPL", "MSFT", "GOOGL", "AMZN")

    # How stale ticker data can be before we re-fetch it (in days).
    ticker_recency_days: int = 14

    # Non-stock asset classes are checked for recency daily: "recent" only
    # means "already fetched today" (max_age_days=0), matching the original
    # check_asset_data_recency, which required version_date == today.
    asset_recency_days: int = 0

    # yfinance history window for price series.
    price_history_period: str = "2y"

    # Asset-class (index/ETF/commodity/FX) price history is fetched in
    # yfinance batch calls rather than one call per symbol, but a single
    # call covering every asset symbol at once has previously triggered
    # Yahoo's rate limiter for the whole batch together. Split into
    # smaller chunks, with a pause between chunks, instead.
    asset_fetch_chunk_size: int = field(
        default_factory=lambda: _env_int("PCT_ASSET_FETCH_CHUNK_SIZE", 5)
    )
    asset_fetch_chunk_delay_seconds: float = field(
        default_factory=lambda: _env_float("PCT_ASSET_FETCH_CHUNK_DELAY_SECONDS", 2.0)
    )

    @property
    def sp500_ticker_csv(self) -> Path:
        return self.data_dir / "sp500_security_ticker.csv"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


# Single shared instance — import this rather than constructing DataConfig() yourself,
# so the whole app agrees on one configuration.
settings = DataConfig()