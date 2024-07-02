import click
import pandas as pd
import os

from .retriever import RetrieveStockData
from .constants import TICKERS


def main(tickers):
    df_comparison = create_main_data(tickers)
    a = 1


def create_main_data(tickers):
    df_ticker_id = pd.read_csv(os.path.expanduser('~/Documents/Code/peer-comparison-tool/data/sp500_security_ticker.csv'))
    ticker_data_list = []
    for ticker in tickers:
        get_stock_data = RetrieveStockData(ticker)
        data_balance_sheets = get_stock_data.balance_sheets
        ticker_overview = get_stock_data.stock_overview_metrics()
        ticker_overview.update({'name': df_ticker_id[df_ticker_id['Symbol'] == ticker]['Security'].iloc[0]})
        ticker_data_list.append(ticker_overview)
        # if get_stock_data.stock_info_key is not None:
        #     click.echo(f"Key stock info for {ticker}: {get_stock_data.stock_info_key}")
    df_ticker_data = pd.DataFrame(ticker_data_list)
    return df_ticker_data


@click.command()
@click.option('--tickers', default=None, prompt='Stock Ticker', help='Pass the stock ticker of the stock you wish to retrieve financial data for')
def execute(tickers):
    if tickers:
        tickers = tickers.split(", ")
    else:
        tickers = TICKERS
    main(tickers)


if __name__ == '__main__':
    main(["AAPL", "AMZN"])
