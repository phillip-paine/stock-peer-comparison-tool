import click
import pandas as pd
import os
from dateutil.relativedelta import relativedelta
from typing import Dict

from .retriever import RetrieveStockData
from .constants import TICKERS
from .utils import apply_dbscan


def main(tickers):
    df_comparison = create_main_data(tickers)
    a = 1


def create_main_data(tickers):
    df_ticker_id = pd.read_csv(os.path.expanduser('~/Documents/Code/peer-comparison-tool/data/sp500_security_ticker.csv'))
    ticker_data_list = []
    df_qfinancials = pd.DataFrame()
    df_balancesheets = pd.DataFrame()
    qfinancials_map: Dict[str, pd.DataFrame] = {}
    balancesheets_map: Dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        get_stock_data = RetrieveStockData(ticker)

        ticker_overview = get_stock_data.add_stock_overview_metrics_to_key_metrics()
        ticker_overview.update({'name': df_ticker_id[df_ticker_id['Symbol'] == ticker]['Security'].iloc[0]})
        ticker_data_list.append(ticker_overview)

        # Write quarterly financials data:
        df_ticker_qfinancial = get_stock_data.get_quarterly_financials_app_data()
        if df_ticker_qfinancial.empty:
            pass
        else:
            add_ticker_metadata(df_ticker_qfinancial, get_stock_data.stock_overview_map)
            if df_qfinancials.empty:
                df_qfinancials = df_ticker_qfinancial
            else:
                df_qfinancials = pd.concat([df_qfinancials, df_ticker_qfinancial])
            df_ticker_complete_qfin = get_stock_data.quarterly_finances
            df_ticker_complete_qfin = df_ticker_complete_qfin.transpose()
            qfinancials_map[ticker] = df_ticker_complete_qfin

        # Balance Sheets:
        df_ticker_balancesheet = get_stock_data.get_balance_sheet_app_data()
        if df_ticker_balancesheet.empty:
            pass
        else:
            add_ticker_metadata(df_ticker_balancesheet, get_stock_data.stock_overview_map)
            if df_balancesheets.empty:
                df_balancesheets = df_ticker_balancesheet
            else:
                df_balancesheets = pd.concat([df_balancesheets, df_ticker_balancesheet])
            df_ticker_complete_bs = get_stock_data.balance_sheets
            df_ticker_complete_bs = df_ticker_complete_bs.transpose()
            balancesheets_map[ticker] = df_ticker_complete_bs

        # if get_stock_data.stock_info_key is not None:
        #     click.echo(f"Key stock info for {ticker}: {get_stock_data.stock_info_key}")
    df_ticker_data = pd.DataFrame(ticker_data_list)

    # Processing todo move to app-processing function or something
    df_qfinancials = df_qfinancials.reset_index().rename(columns={'index': 'date'})
    df_qfinancials['date_moved'] = df_qfinancials['date'] - pd.DateOffset(months=1)
    df_qfinancials['date'] = df_qfinancials['date_moved'].dt.year.astype(str) + "_" + df_qfinancials['date_moved'].dt.quarter.astype(str)
    # todo quarterly mapping - tough because different end of months for reporting
    df_balancesheets = df_balancesheets.reset_index().rename(columns={'index': 'date'})
    df_balancesheets['date_moved'] = df_balancesheets['date'] + pd.DateOffset(months=3)
    df_balancesheets['date'] = df_balancesheets['date_moved'].dt.year.astype(str)
    df_ticker_data['market_cap_MM'] = df_ticker_data['market_cap'] / 1_000_000  # in millions
    df_qfinancials['Operating Income (MM)'] = df_qfinancials['Operating Income'] / 1_000_000  # in millions

    # clustering for scatter chart:
    df_ticker_data = apply_dbscan(df=df_ticker_data,
                                  cols=["price_eps_ratio", "latest_eps", "return_on_equity", "EV_EBIDTA", "market_cap_MM"],
                                  eps=0.5,
                                  min_samples=3)

    return df_ticker_data, df_qfinancials, df_balancesheets, qfinancials_map, balancesheets_map


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
