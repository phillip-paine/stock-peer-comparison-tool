import click
import pandas as pd
import os

from data.constants import TICKERS
from data.main import create_main_data
from comparison_tool.app import create_app

from typing import Optional, Dict


def main_run(tickers_subgics_map: Optional[Dict[str, str]] = None):
    if tickers_subgics_map is None:
        tickers_subgics_map = {ticker: "Misc." for ticker in TICKERS}
    ticker_series_data, df_ticker_metrics, df_ticker_quarterly_ts, df_ticker_balance_sheet_ts, quarterlyfin_map, balancesheet_map, cashflow_map = create_main_data(tickers_subgics_map)
    app = create_app(ticker_series_data, df_ticker_metrics, df_ticker_quarterly_ts, df_ticker_balance_sheet_ts, quarterlyfin_map, balancesheet_map, cashflow_map)
    app.run_server(debug=True)
    a=1


@click.command()
@click.option('--tickers', default=None, prompt='Stock Ticker', help='Pass the stock ticker of the stock you wish to retrieve financial data for')
def execute_app(tickers):
    # TODO out of date - will not run from CLI currently
    if tickers:
        tickers = tickers.split(", ")
    else:
        tickers = TICKERS
    df_ticker_metrics, df_ticker_qfinancials = create_main_data(tickers)
    app = create_app(df_ticker_metrics, df_ticker_qfinancials)
    app.run_server(debug=True)


if __name__ == '__main__':
    df_ticker_id = pd.read_csv(os.path.expanduser('~/Documents/Code/peer-comparison-tool/data/sp500_security_ticker.csv'))
    # df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Utilities"]
    df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Health Care"]
    map_tickers_subindustry = dict(zip(df_ticker_id['Symbol'], df_ticker_id['GICS Sub-Industry']))
    # tickers = ["AAPL", "MSFT", "AMZN", "NVDA", "META"]
    main_run(map_tickers_subindustry)
