TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN"]

# Non-stock asset universe: yfinance symbol -> friendly display name, grouped
# by asset class. Was previously constructed inline inside
# RetrieveEconomicsData.__init__ every time that class was instantiated.
ASSET_CLASS_TICKERS: dict[str, dict[str, str]] = {
    "commodity": {
        "GC=F": "GoldFutures",
        "BZ=F": "CrudeOilFutures",
        "NG=F": "NaturalGasFutures",
        "ZW=F": "WheatFutures",
    },
    "index_fund": {
        "^GSPC": "S&P500_Index",
        "^DJI": "DowJones_Index",
        "^IXIC": "NASDAQ_Index",
        "^RUT": "Russell2000_Index",
    },
    "etf": {
        "SPY": "S&P500_ETF",
        "QQQ": "NASDAQ_ETF",
        "IWM": "Russell2000_ETF",
        "XLK": "TechSector",
        "XLF": "Financial_Sector",
        "XLE": "Energy_Sector",
        "XLV": "HealthCare_Sector",
        "XLY": "ConsumerDiscretionary_Sector",
    },
    "fx": {
        "EURUSD=X": "EuroUSD_fx",
        # USD per 1 CAD -- the rate the portfolio page uses to express CAD
        # positions in USD (see data/transforms/portfolio.FX_SERIES_BY_CURRENCY).
        "CADUSD=X": "CADUSD_fx",
    },
    # Treasury yield curve. yfinance exposes these as regular index tickers
    # (same fetch path as everything else above -- no new client needed),
    # unlike genuine economic release data (CPI, JOLTS, payrolls, etc.),
    # which yfinance doesn't have at all -- see data/clients/fred_client.py.
    "rate": {
        "^IRX": "US13W_Yield",
        "^FVX": "US5Y_Yield",
        "^TNX": "US10Y_Yield",
        "^TYX": "US30Y_Yield",
    },
}


def asset_symbols() -> list[str]:
    """All yfinance symbols across every asset class, e.g. ['GC=F', 'BZ=F', ...]."""
    return [symbol for group in ASSET_CLASS_TICKERS.values() for symbol in group]


def asset_symbol_to_name() -> dict[str, str]:
    """yfinance symbol -> friendly display name, e.g. {'GC=F': 'GoldFutures'}."""
    return {symbol: name for group in ASSET_CLASS_TICKERS.values() for symbol, name in group.items()}


def asset_name_to_class() -> dict[str, str]:
    """Friendly display name -> asset class, e.g. {'GoldFutures': 'commodity'}."""
    return {
        name: asset_class
        for asset_class, group in ASSET_CLASS_TICKERS.items()
        for name in group.values()
    }
