import sqlite3
import pandas as pd


#Tables that we will create:
# Company data: this is fixed data that most likely will not change (ticker, name, industry, sub-industry etc.)
# quarterly report data (df_ticker_data) : ticker, date_of_report, quarterly report (market cap, etc)
# balance sheet : same as above but for balance sheet
# time series ticker stock prices + sub-industry aggregates
# Sub-industry aggregations?
## - there is also the question of when we compute metrics from Q and K report items
# seems best to create them when we fetch the data and then just read them into the app data
#

def initialize_db_connection(db_name=None):
    # Connect to SQLite (or create the database if it doesn't exist)
    if db_name is None:
        raise ValueError("Must supply a db name to begin connection")
    conn = sqlite3.connect(db_name)
    print(f'Connection to {db_name} created.')
    return conn


def close_db(conn, db_name=None):
    if db_name is None:
        print('Please give the database name')
        return None
    conn.close()
    print(f'Connection to {db_name} closed.')
