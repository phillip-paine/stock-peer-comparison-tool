import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from .queries import query_ticker_time_series_yoy, query_create_industry_price_aggregation, \
    query_create_industry_price_yoy_aggregation, query_create_industry_metric_aggregation

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

    cur = conn.cursor()
    cur.execute("""SELECT MAX("version date") from data_storage_record where ticker = ?""", (ticker, ))
    result = cur.fetchone()
    cur.close()

    # today date
    date_today = datetime.now().date()
    if result[0] is None or (datetime.strptime(result[0], "%Y-%m-%d").date() < date_today - relativedelta(days=14)):
        # print("No recent data versions found - retrieving new data")
        return False

    else:
        # print("Recent data found - not retrieving new data")
        return True


def check_asset_data_recency(conn, ticker) -> bool:
    cur = conn.cursor()
    cur.execute("""SELECT MAX("version date") from data_storage_record where ticker = ?""", (ticker, ))
    result = cur.fetchone()
    cur.close()

    # today date
    date_today = datetime.now().date()
    if result[0] is None or (datetime.strptime(result[0], "%Y-%m-%d").date() < date_today):
        # print("No recent data versions found - retrieving new data")
        return False

    else:
        # print("Recent data found - not retrieving new data")
        return True


def update_ticker_yoy_aggregations(sql_conn):
    cur = sql_conn.cursor()
    cur.execute(query_ticker_time_series_yoy)
    # lets do this outside of query:
    df_quarter = fetch_table_data(sql_conn, 'quarterly_financial_data', force_date_conversion=True)
    df_quarter_lagged = df_quarter.copy()
    df_quarter_lagged['date'] = pd.to_datetime(df_quarter_lagged['date']) + pd.DateOffset(years=1)
    df_quarter_lagged['date_moved'] = df_quarter_lagged['date'] - pd.DateOffset(months=1)
    df_quarter_lagged['quarter_reporting'] = df_quarter_lagged['date_moved'].dt.year.astype(str) + "_" + df_quarter_lagged['date_moved'].dt.quarter.astype(str)
    df_quarter_yoy = pd.merge(df_quarter, df_quarter_lagged, on=['ticker', 'quarter_reporting'], suffixes=('', '_lagged'))
    yoy_metric_cols = ['Basic EPS', 'Operating Income', 'Net Income', 'Gross Margin', 'Operating Margin', 'Net Margin', 'EBITDA Margin']
    for metric_col in yoy_metric_cols:
        df_quarter_yoy[f'{metric_col} YoY'] = np.where(df_quarter_yoy[f'{metric_col}_lagged'] != 0, (df_quarter_yoy[f'{metric_col}'] / df_quarter_yoy[f'{metric_col}_lagged'] - 1) * 100, 0)
    yoy_metric_cols = [col + ' YoY' for col in yoy_metric_cols]
    insert_or_ignore(cur, 'ticker_metrics_yoy', df_quarter_yoy[['ticker', 'date', 'quarter_reporting'] + yoy_metric_cols])
    cur.close()
    return


def update_industry_aggregations(sql_conn):
    # here we just merge on the industry to each ticker and then aggregate:
    cur = sql_conn.cursor()
    cur.execute(query_create_industry_price_aggregation)
    cur.execute(query_create_industry_price_yoy_aggregation)
    cur.execute(query_create_industry_metric_aggregation)
    # TODO move this to a create_metrics_yoy_func
    df_quarter = fetch_table_data(sql_conn, 'industry_metrics', force_date_conversion=True)
    df_quarter_lagged = df_quarter.copy()
    df_quarter_lagged['date'] = pd.to_datetime(df_quarter_lagged['date']) + pd.DateOffset(years=1)
    df_quarter_lagged['date_moved'] = df_quarter_lagged['date'] - pd.DateOffset(months=1)
    df_quarter_lagged['quarter_reporting'] = df_quarter_lagged['date_moved'].dt.year.astype(str) + "_" + df_quarter_lagged['date_moved'].dt.quarter.astype(str)
    df_quarter_yoy = pd.merge(df_quarter, df_quarter_lagged, on=['sub_industry', 'quarter_reporting'], suffixes=('', '_lagged'))
    yoy_metric_cols = ['Basic EPS', 'Operating Income', 'Net Income', 'Gross Margin', 'Operating Margin', 'Net Margin', 'EBITDA Margin']
    for metric_col in yoy_metric_cols:
        df_quarter_yoy[f'{metric_col} YoY'] = np.where(df_quarter_yoy[f'{metric_col}_lagged'] != 0, (df_quarter_yoy[f'{metric_col}'] / df_quarter_yoy[f'{metric_col}_lagged'] - 1) * 100, 0)
    yoy_metric_cols = [col + ' YoY' for col in yoy_metric_cols]
    insert_or_ignore(cur, 'industry_metrics_yoy', df_quarter_yoy[['sub_industry', 'date', 'quarter_reporting'] + yoy_metric_cols])
    cur.close()
    return


def update_other_asset_classes(retriever, conn):
    cur = conn.cursor()
    if retriever.non_stock_entities:
        df = retriever.retrieve_economic_data()
        insert_or_ignore(cur, 'asset_class_time_series', df)
    record_data_cols = ['ticker', 'version date']
    record_data_saved = pd.DataFrame(
        {'ticker': list(retriever.non_stock_entities.keys()),
         'version date': [date.today().strftime("%Y-%m-%d")]*len(list(retriever.non_stock_entities.keys()))}
    )
    insert_or_ignore(cur, 'data_storage_record', record_data_saved[record_data_cols])
    conn.commit()
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


def fetch_table_data(sql_conn, table_name, date: str = None, most_recent: bool = False, force_date_conversion: bool = False):
    # Use string formatting to dynamically set the table name
    query = f"SELECT * FROM {table_name}"
    if most_recent:
        query = f"WITH RecentDates AS (SELECT ticker, max(date) as max_date FROM cluster_table GROUP BY ticker) " \
                f"SELECT t1.* from {table_name} as t1 JOIN RecentDates as rd on t1.ticker = rd.ticker and " \
                f"t1.date = rd.max_date"

    if not most_recent and date:
        query = f"SELECT *, datetime(date / 1000000000, 'unixepoch') as date_type FROM {table_name} where date_type >= {date}"

    # Execute the query and load into a DataFrame
    df = pd.read_sql_query(query, sql_conn)
    if 'date' in df.columns and (df['date'].dtype == 'int' or force_date_conversion):
        try:
            df = unix_to_date_format(df, 'date')  # always 'date' column name?
        except Exception as E:
            print(E)
    return df


def unix_to_date_format(df: pd.DataFrame, date_col: str):
    # It is in unix timestamps, first get to seconds and then convert to str format:
    df[date_col] = pd.to_datetime(df[date_col].astype(int) // 10**9, unit='s').dt.strftime('%Y-%m-%d')
    # need to drop duplicates now? This seems like an issue with reading or writing to SQL..
    return df
