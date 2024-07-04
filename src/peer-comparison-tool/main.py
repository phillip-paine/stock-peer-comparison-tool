import click
import pandas as pd
import os

from data.constants import TICKERS
from data.main import create_main_data
from comparison_tool.app import create_app

from typing import Optional, Any


def main_run(tickers: Optional[Any] = None):
    if tickers is None:
        tickers = TICKERS
    df_ticker_metrics = create_main_data(tickers)
    app = create_app(df_ticker_metrics)
    app.run_server(debug=True)
    a=1


@click.command()
@click.option('--tickers', default=None, prompt='Stock Ticker', help='Pass the stock ticker of the stock you wish to retrieve financial data for')
def execute_app(tickers):
    if tickers:
        tickers = tickers.split(", ")
    else:
        tickers = TICKERS
    df_ticker_metrics = create_main_data(tickers)
    app = create_app(df_ticker_metrics)
    app.run_server(debug=True)


if __name__ == '__main__':
    df_ticker_id = pd.read_csv(os.path.expanduser('~/Documents/Code/peer-comparison-tool/data/sp500_security_ticker.csv'))
    df_ticker_id = df_ticker_id.sample(n=50)
    tickers = df_ticker_id['Symbol']
    main_run(tickers)
