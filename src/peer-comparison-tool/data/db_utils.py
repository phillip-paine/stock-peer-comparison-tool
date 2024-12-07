import sqlite3
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta

from queries import query_ticker_yoy, query_industry_aggregation

YOY_METRICS = ['close_price', 'close_price_indexed']


# Function to insert quarterly report data into the SQLite database
def insert_quarterly_data(db_name, ticker, data):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    for row in data.itertuples():
        cursor.execute('''
            INSERT OR IGNORE INTO quarterly_reports (ticker, date, eps, revenue, net_income)
            VALUES (?, ?, ?, ?, ?)
        ''', (ticker, row.Index.strftime('%Y-%m-%d'), row.Earnings, row.Revenue, row.NetIncome))

    conn.commit()
    conn.close()


# Function to read data from the SQLite database into a pandas DataFrame
# We likely want a function for each type of request:
def read_ticker_from_db_table(db_name, table, ticker):
    conn = sqlite3.connect(db_name)
    query = f"SELECT * FROM {table} WHERE ticker = '{ticker}'"
    df = pd.read_sql(query, conn)
    conn.close()
    return df


def check_ticker_data_recency(conn, ticker) -> bool:
    # TODO temp fix until finished creating this table
    if ticker is not None:
        return False
    cur = conn.cursor()
    cur.execute("SELECT MAX(version_date) from data_storage_record where ticker = ?", (ticker, ))
    result = cur.fetchone()
    cur.close()

    # today date
    date_today = datetime.now().date()
    if result[0] is None or (result[0] < date_today - relativedelta(days=14)):
        print("No recent data versions found - retrieving new data")
        return True

    else:
        print("Recent data found - not retrieving new data")
        return False


def update_yoy_aggregations(sql_conn):
    cur = sql_conn.cursor()
    cur.execute(query_ticker_yoy)
    cur.close()
    return


def update_industry_aggregations(sql_conn):
    # here we just merge on the industry to each ticker and then aggregate:
    cur = sql_conn.cursor()
    cur.execute(query_industry_aggregation)
    cur.close()
    return


def insert_or_replace(cursor, table, data):
    # Some columns have spaces so we need to set column strings correctly first:
    columns = [f'"{col}"' for col in data.columns]
    columns_str = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(data.columns))
    sql = f"INSERT OR REPLACE INTO {table} ({columns_str}) VALUES ({placeholders})"
    cursor.executemany(sql, data.to_records(index=False).tolist())


def insert_or_ignore(cursor, table, dataframe):
    columns = [f'"{col}"' for col in dataframe.columns]
    columns_str = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(dataframe.columns))
    sql = f"INSERT OR IGNORE INTO {table} ({columns_str}) VALUES ({placeholders})"
    cursor.executemany(sql, dataframe.to_records(index=False).tolist())
