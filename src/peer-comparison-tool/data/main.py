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
    df_qfinancials = pd.DataFrame()
    for ticker in tickers:
        get_stock_data = RetrieveStockData(ticker)
        # data_balance_sheets = get_stock_data.balance_sheets
        ticker_overview = get_stock_data.add_stock_overview_metrics_to_key_metrics()
        ticker_overview.update({'name': df_ticker_id[df_ticker_id['Symbol'] == ticker]['Security'].iloc[0]})
        ticker_data_list.append(ticker_overview)
        # Write quarterly financials data:
        df_ticker_qfinancial = get_stock_data.get_quarterly_financials_app_data()
        add_ticker_metadata(df_ticker_qfinancial, get_stock_data.stock_overview_map)
        if df_qfinancials.empty:
            df_qfinancials = df_ticker_qfinancial
        else:
            df_qfinancials = pd.concat([df_qfinancials, df_ticker_qfinancial])

        # if get_stock_data.stock_info_key is not None:
        #     click.echo(f"Key stock info for {ticker}: {get_stock_data.stock_info_key}")
    df_ticker_data = pd.DataFrame(ticker_data_list)
    df_qfinancials = df_qfinancials.reset_index().rename(columns={'index': 'date'})
    return df_ticker_data, df_qfinancials


def add_ticker_metadata(df: pd.DataFrame, ticker_metadata):
    for key, val in ticker_metadata.items():
        df[key] = val


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
