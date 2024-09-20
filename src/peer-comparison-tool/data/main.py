import click
import pandas as pd
import numpy as np
import os
from typing import Dict, Any

from .retriever import RetrieveStockData
from .constants import TICKERS
from .utils import create_valuation_clusters


def main(tickers):
    df_comparison = create_main_data(tickers)
    a = 1


def create_main_data(tickers_info_map):
    gics_subindustry_list = list(set(tickers_info_map.values()))
    df_ticker_id = pd.read_csv(os.path.expanduser('~/Documents/Code/peer-comparison-tool/data/sp500_security_ticker.csv'))
    ticker_data_list = []
    ticker_data_series_maps: Dict[str, Any] = {}
    df_qfinancials = pd.DataFrame()
    df_balancesheets = pd.DataFrame()
    qfinancials_map: Dict[str, pd.DataFrame] = {}
    balancesheets_map: Dict[str, pd.DataFrame] = {}
    cashflow_map: Dict[str, pd.DataFrame] = {}
    tickers_list = list(tickers_info_map.keys())
    for ticker, subindustry in tickers_info_map.items():
        get_stock_data = RetrieveStockData(ticker)

        ticker_overview = get_stock_data.add_stock_overview_metrics_to_key_metrics()
        ticker_overview.update({'name': df_ticker_id[df_ticker_id['Symbol'] == ticker]['Security'].iloc[0]})
        ticker_overview.update({'Sub-industry': subindustry})
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

        # Cash Flow Statement:
        df_ticker_cashflow = get_stock_data.get_cashflow_data()
        if df_ticker_cashflow.empty:
            pass
        else:
            cashflow_map[ticker] = df_ticker_cashflow

        # get stock series and year-to-year change data
        try:
            ticker_data_series_maps.update({ticker: get_stock_data.get_stock_level_data()})
        except IndexError as e:
            print(f"{e} for {ticker} during get_stock_data call")

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
    cluster_cols = ["price_eps_ratio", "latest_eps", "return_on_equity", "enterpriseToEbitda", "debt_to_equity_ratio", "profit_margin"]
    df_ticker_data = create_valuation_clusters(df=df_ticker_data, cols=cluster_cols, eps=0.5, min_samples=3)

    # industry average change:
    # def calc_decimal_change(pct):
    #     return 1 + pct/100

    num_keys = len(ticker_data_series_maps)
    ticker_data_series_maps['industry'] = {}
    ticker_data_series_used = list(ticker_data_series_maps.keys())
    for yoy_metric in list(ticker_data_series_maps[tickers_list[0]].keys()):
        if yoy_metric not in ['stock_price_data', 'stock_price_normalised_data']:
            ticker_data_series_maps['industry'].update({
                f"{yoy_metric}": np.mean([ticker_data_series_maps[tcker].get(yoy_metric, 1) for tcker in ticker_data_series_used])
            })
        else:
            # calculate the industry price index and normalise:
            # todo this assumes that all tickers are from the same industry - now generalise this so it uses the
            # todo sub-industry groupings - maybe save one column for each subindustry_close time series
            industry_price_df = ticker_data_series_maps[tickers_list[0]][yoy_metric]
            for ticker in ticker_data_series_used:
                try:
                    df_temp = ticker_data_series_maps[ticker][yoy_metric]
                    df_temp[f'Close_{ticker}'] = df_temp['Close']
                    industry_price_df = pd.merge(industry_price_df,
                                                 df_temp[['Date', f'Close_{ticker}']],
                                                 on=['Date'])
                except KeyError as e:
                    print(f"{e} for {ticker} when calculating YoY values")
            for sub_industry in gics_subindustry_list:
                sub_industry_cols = [c for c in industry_price_df.columns if c.startswith('Close') and any(substr in c for substr in sub_industry)]
                sub_industry_price_col = f'{sub_industry} Close'
                industry_price_df[sub_industry_price_col] = industry_price_df[sub_industry_cols].sum(axis=1)
                industry_price_df[sub_industry_price_col] = industry_price_df[sub_industry_price_col] / industry_price_df[sub_industry_price_col].iloc[0] * 100
                ticker_data_series_maps[f'Industry Index:{sub_industry}'] = {
                    yoy_metric: industry_price_df[['Date', sub_industry_price_col]]
                }
                # todo then we can use the subindustry time series of close (and other metrics?) in the app home_page

    return ticker_data_series_maps, df_ticker_data, df_qfinancials, df_balancesheets, qfinancials_map, balancesheets_map, cashflow_map


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
    main({"AAPL": "testA", "AMZN": "testB"})
