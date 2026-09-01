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
