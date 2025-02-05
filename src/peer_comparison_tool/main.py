import click
import pandas as pd
import os

from data.constants import TICKERS
from comparison_tool.constants import DB_PATH
from data.main import create_ticker_data, create_aggregations_data
from comparison_tool.app import create_app
from data.db import initialize_db_connection, close_db
from data.db_utils import check_ticker_data_recency, check_asset_data_recency, update_other_asset_classes

from typing import Optional, Dict

from src.peer_comparison_tool.data.retriever import RetrieveEconomicsData


def main_run(tickers_subgics_map: Optional[Dict[str, str]] = None):
    if tickers_subgics_map is None:
        tickers_subgics_map = {ticker: "Misc." for ticker in TICKERS}

    try:
        sql_conn = initialize_db_connection(DB_PATH)
        ticker_subgics_retrieve_data_map = {}
        ticker_subgics_already_retrieved_map = {}
        for ticker in list(tickers_subgics_map.keys()):
            if check_ticker_data_recency(sql_conn, ticker):
                ticker_subgics_already_retrieved_map[ticker] = tickers_subgics_map[ticker]
            else:
                ticker_subgics_retrieve_data_map[ticker] = tickers_subgics_map[ticker]

    except ValueError as e:
        print(e)
        return

    # fetch new data,transform and write to tables then update aggregations such as industry time series etc:
    if ticker_subgics_retrieve_data_map:
        create_ticker_data(ticker_subgics_retrieve_data_map, sql_conn)  # TODO uncomment
        # rerun aggregations, clustering, other ML models etc. if needed to store updated summaries and features:
        create_aggregations_data(sql_conn, tickers_subgics_map)

    asset_retriever = RetrieveEconomicsData()
    for asset in list(asset_retriever.non_stock_entities.keys()):
        if check_asset_data_recency(sql_conn, asset):
            del asset_retriever.non_stock_entities[asset]  # remove from the map

    update_other_asset_classes(asset_retriever, sql_conn)

    # then we only need to pass the sqlite connection to the create_app then we can query data when we need it:
    app = create_app(sql_conn)
    app.run_server(debug=True)
    close_db(sql_conn, DB_PATH)
    return


@click.command()
@click.option('--tickers', default=None, prompt='Stock Ticker', help='Pass the stock ticker of the stock you wish to retrieve financial data for')
def execute_app(tickers):
    # TODO out of date - will not run from CLI currently
    if tickers:
        tickers = tickers.split(", ")
    else:
        tickers = TICKERS
    df_ticker_metrics, df_ticker_qfinancials = create_ticker_data(tickers)
    app = create_app(df_ticker_metrics, df_ticker_qfinancials)
    app.run_server(debug=True)


if __name__ == '__main__':
    df_ticker_id = pd.read_csv(os.path.expanduser('~/Documents/Code/peer-comparison-tool/data/sp500_security_ticker.csv'))
    # df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Utilities"]
    # df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Materials"]
    # df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Health Care"]
    # df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Financials"]
    # df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Industrials"]
    # df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Energy"]
    # df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Consumer Staples"]
    df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Information Technology"]
    map_tickers_subindustry = dict(zip(df_ticker_id['Symbol'], df_ticker_id['GICS Sub-Industry']))
    # tickers = ["AAPL", "MSFT", "AMZN", "NVDA", "META"]
    # map_tickers_subindustry = {'ELV': 'Managed Health Care', 'STE': 'Health Care Equipment',
    #                            'TFX': 'Health Care Equipment'}
    main_run(map_tickers_subindustry)
