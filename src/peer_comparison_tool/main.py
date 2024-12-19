import click
import pandas as pd
import os

from data.constants import TICKERS
from data.main import create_ticker_data, create_aggregations_data
from comparison_tool.app import create_app
from data.db import initialize_db_connection, close_db
from data.db_utils import check_ticker_data_recency

from typing import Optional, Dict

db_folder = os.path.join(os.path.dirname(__file__), "comparison_tool")
db_path = os.path.join(db_folder, "comparison_tool.db")


def main_run(tickers_subgics_map: Optional[Dict[str, str]] = None):
    if tickers_subgics_map is None:
        tickers_subgics_map = {ticker: "Misc." for ticker in TICKERS}

    try:
        sql_conn = initialize_db_connection(db_path)
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

    # create new data and write to tables:
    if ticker_subgics_retrieve_data_map is not None:
        create_ticker_data(ticker_subgics_retrieve_data_map, sql_conn)

    # rerun aggregations, clustering, other ML models etc. if needed to store updated summaries and features:
    create_aggregations_data(sql_conn, tickers_subgics_map)

    # then we only need to pass the sqlite connection to the create_app then we can query data when we need it:
    app = create_app(sql_conn)
    app.run_server(debug=True)
    close_db(sql_conn, db_path)
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
    df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Health Care"]
    map_tickers_subindustry = dict(zip(df_ticker_id['Symbol'], df_ticker_id['GICS Sub-Industry']))
    # tickers = ["AAPL", "MSFT", "AMZN", "NVDA", "META"]
    # map_tickers_subindustry = {'ELV': 'Managed Health Care', 'STE': 'Health Care Equipment',
    #                            'TFX': 'Health Care Equipment'}
    main_run(map_tickers_subindustry)
