from db import initialize_db_connection, close_db
import os


def create_company_table(conn):
    cur = conn.cursor()
    # query_drop = "DROP TABLE IF EXISTS company_info;"
    # cur.execute(query_drop)
    query = """
        CREATE TABLE IF NOT EXISTS company_info (
            ticker TEXT NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            sector TEXT NOT NULL,
            industry TEXT,
            sub_industry TEXT
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print('Created table Company table.')


def create_ticker_time_series_table(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS ticker_time_series;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS ticker_time_series (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close_price REAL,
            close_price_indexed REAL,
            FOREIGN KEY (ticker) REFERENCES company_info(ticker),
            PRIMARY KEY (ticker, date)
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print('Create ticker time series table')


def create_asset_class_ts_table(conn):
    cur = conn.cursor()

    # query_drop = "DROP TABLE IF EXISTS asset_class_time_series;"
    # cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS asset_class_time_series (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            AssetClass TEXT,
            close_price REAL,
            close_price_indexed REAL,
            close_price_yoy REAL,
            PRIMARY KEY(ticker, date)
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print('Create asset class time series table')


def create_quarterly_report_financial_data(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS quarterly_financial_data;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS quarterly_financial_data (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            quarter_reporting TEXT NOT NULL,
            "Basic EPS" REAL,
            "Operating Income" REAL,
            "Operating Income (MM)" REAL,
            "Net Income" REAL,
            "Net Income (MM)" REAL,
            "Gross Margin" REAL,
            "Operating Margin" REAL,
            "Net Margin" REAL,
            "EBITDA Margin" REAL,
            PRIMARY KEY (ticker, date)
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print('Create quarterly financials table')


def create_balance_sheet_report_data(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS balance_sheet_data;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS balance_sheet_data (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            annual_reporting TEXT NOT NULL,
            "OrdinarySharesNumber" INTEGER,
            "StockholdersEquity" INTEGER,
            TotalLiabilitiesNetMinorityInterest REAL,
            "CurrentAssets" REAL,
            "Quick Ratio" REAL,
            "Equity Ratio" REAL,
            "Debt-to-Equity Ratio" REAL,
            PRIMARY KEY (ticker, date)
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print('Create balance sheet table')


def create_cashflow_statement(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS cashflow_statement_data;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS cashflow_statement_data (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            "Free Cash Flow" REAL,
            "Operating Cash Flow" REAL,
            "Capital Expenditure" REAL,
            PRIMARY KEY (ticker, date)
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print("Create cash flow statement table")


def create_tickers_most_recent_metrics(conn):
    # This is taken from the most recent data for the ticker:
    # TODO delete and remake - should look up how to do migrations i guess

    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS ticker_most_recent_metric_data;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS ticker_most_recent_metric_data (
            ticker TEXT NOT NULL PRIMARY KEY,
            market_cap REAL,
            price_eps_ratio REAL,
            price_to_book REAL,
            return_on_equity REAL,
            debt_to_equity_ratio REAL,
            profit_margin REAL,
            enterpriseToEbitda REAL,
            latest_eps REAL,
            enterprise_value REAL 
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print("Create ticker most recent metrics table")


def create_cluster_data(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS cluster_table;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS cluster_table (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            cluster_membership SMALLINT,
            PRIMARY KEY (ticker, date)
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print("Create cluster membership table")


def create_ticker_ts_yoy(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS ticker_ts_yoy;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS ticker_ts_yoy (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close_price_yoy REAL,
            close_price_indexed_yoy REAL,
            PRIMARY KEY (ticker, date) 
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print("Create cluster membership table")


def create_industry_aggregated_time_series_table(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS industry_time_series;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS industry_time_series (
            sub_industry TEXT NOT NULL,
            date TEXT NOT NULL,
            industry_close_price REAL,
            industry_close_price_indexed REAL,
            PRIMARY KEY (sub_industry, date)
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print("Create industry aggregated price table")


def create_industry_aggregated_ts_yoy(conn):

    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS industry_time_series_yoy;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS industry_time_series_yoy (
            sub_industry TEXT NOT NULL,
            date TEXT NOT NULL,
            industry_close_price_yoy REAL,
            industry_close_price_indexed_yoy REAL,
            PRIMARY KEY (sub_industry, date) 
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print("Create industry aggregated yoy price table")


def create_ticker_report_yoy_data(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS ticker_metrics_yoy;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS ticker_metrics_yoy (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            quarter_reporting TEXT NOT NULL,
            "Basic EPS YoY" REAL,
            "Operating Income YoY" REAL,
            "Net Income YoY" REAL,
            "Gross Margin YoY" REAL,
            "Operating Margin YoY" REAL,
            "Net Margin YoY" REAL,
            "EBITDA Margin YoY" REAL,
            PRIMARY KEY (ticker, date)
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print('Create individual ticker YoY table')


def create_industry_report_metrics_data(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS industry_metrics;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS industry_metrics (
            sub_industry TEXT NOT NULL,
            date TEXT NOT NULL,
            quarter_reporting TEXT NOT NULL,
            "Basic EPS" REAL,
            "Operating Income" REAL,
            "Net Income" REAL,
            "Gross Margin" REAL,
            "Operating Margin" REAL,
            "Net Margin" REAL,
            "EBITDA Margin" REAL,
            PRIMARY KEY (sub_industry, date)
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print('Create industry metrics table')


def create_industry_report_yoy_data(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS industry_metrics_yoy;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS industry_metrics_yoy (
            sub_industry TEXT NOT NULL,
            date TEXT NOT NULL,
            quarter_reporting TEXT NOT NULL,
            "Basic EPS YoY" REAL,
            "Operating Income YoY" REAL,
            "Net Income YoY" REAL,
            "Gross Margin YoY" REAL,
            "Operating Margin YoY" REAL,
            "Net Margin YoY" REAL,
            "EBITDA Margin YoY" REAL,
            PRIMARY KEY (sub_industry, date)
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print('Create industry metrics YoY table')


def create_data_record_table(conn):
    cur = conn.cursor()

    query_drop = "DROP TABLE IF EXISTS data_storage_record;"
    cur.execute(query_drop)

    query = """
        CREATE TABLE IF NOT EXISTS data_storage_record (
            ticker TEXT NOT NULL,
            "version date" TEXT NOT NULL,
            PRIMARY KEY (ticker, "version date") 
        )
    """
    cur.execute(query)
    conn.commit()
    cur.close()
    print('Create date record table')


# We need the aggregated tables that are created every time data is updated:
# this is things like the industry/sub-industry totals etc.
# also need to recreate the cluster labels

if __name__ == '__main__':
    # Script to create tables:
    db_folder = os.path.join(os.path.dirname(__file__), "..", "comparison_tool")
    db_path = os.path.join(db_folder, "comparison_tool.db")
    db_conn = initialize_db_connection(db_path)

    # create_company_table(db_conn)  # done
    # create_ticker_time_series_table(db_conn)  # done
    # create_quarterly_report_financial_data(db_conn)
    # create_balance_sheet_report_data(db_conn)
    # create_cashflow_statement(db_conn)
    # create_cluster_data(db_conn)
    # create_ticker_ts_yoy(db_conn)
    # create_data_record_table(db_conn)
    # create_tickers_most_recent_metrics(db_conn)
    # create_industry_aggregated_time_series_table(db_conn)
    # create_industry_aggregated_ts_yoy(db_conn)
    # create_ticker_report_yoy_data(db_conn)
    # create_industry_report_metrics_data(db_conn)
    # create_industry_report_yoy_data(db_conn)
    create_asset_class_ts_table(db_conn)

    # print the names of all tables in the db:
    cursor = db_conn.cursor()
    cursor.execute("SELECT * from sqlite_master WHERE type='table';")

    tables = cursor.fetchall()
    for table in tables:
        print(f'table name: {table[1]}')
    cursor.close()
    close_db(db_conn, db_path)
