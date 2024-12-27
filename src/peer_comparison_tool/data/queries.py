query_create_industry_price_aggregation = """
    WITH ticker_sector_price as (
        SELECT TTS.*, CI.sub_industry FROM ticker_time_series as TTS 
        JOIN (SELECT ticker, sub_industry from company_info) as CI ON TTS.ticker = CI.ticker
    ),
    
    industry_aggregate_price as (
        SELECT sub_industry, date, sum(close_price) as industry_close_price, sum(close_price_indexed) as industry_close_price_indexed
        FROM ticker_sector_price
        GROUP BY sub_industry, date
    )
    
    INSERT OR IGNORE INTO industry_time_series (sub_industry, date, industry_close_price, industry_close_price_indexed)
    select * from industry_aggregate_price
"""

query_create_industry_price_yoy_aggregation = """
    WITH industry_price_year_lag as (
        SELECT t1.*, t2.industry_close_price as close_price_year, t2.industry_close_price_indexed as close_price_indexed_year
        FROM industry_time_series as t1
        JOIN (select *, date(date, '+1 YEAR') as date_lagged 
            from industry_time_series) as t2
        ON t1.sub_industry = t2.sub_industry AND t1.date = t2.date_lagged
    ),
    temp_industry_price_yoy as (
        SELECT sub_industry, date, (industry_close_price / close_price_year - 1) as industry_close_price_yoy, 
            (industry_close_price_indexed / close_price_indexed_year - 1) as industry_close_price_indexed_yoy
        FROM industry_price_year_lag
    ) 
    INSERT OR IGNORE INTO industry_time_series_yoy (sub_industry, date, industry_close_price_yoy, industry_close_price_indexed_yoy) 
    SELECT * FROM temp_industry_price_yoy 
"""

query_create_industry_metric_aggregation = """
    WITH temp_quarterly_sector_financials as (
        SELECT * FROM quarterly_financial_data as QFD JOIN (SELECT ticker, sub_industry FROM company_info) as CI on QFD.ticker = CI.ticker
    ),
    temp_industry_financials as (
        SELECT sub_industry, MIN(date) as date, quarter_reporting, 
            AVG(\"Basic EPS\") as \"Basic EPS\", AVG(\"Operating Income\") as \"Operating Income\",
            AVG(\"Net Income\") as \"Net Income\", AVG(\"Gross Margin\") as \"Gross Margin\",
            AVG(\"Operating Margin\") as \"Operating Margin\",
            AVG(\"Net Margin\") as \"Net Margin\", AVG(\"EBITDA Margin\") as \"EBITDA Margin\"
        FROM temp_quarterly_sector_financials
        GROUP BY sub_industry, quarter_reporting
    )
    INSERT OR IGNORE INTO industry_metrics (sub_industry, date, quarter_reporting, \"Basic EPS\", \"Operating Income\", \"Net Income\", 
        \"Gross Margin\", \"Operating Margin\", \"Net Margin\", \"EBITDA Margin\") 
    SELECT * FROM temp_industry_financials 
"""

query_ticker_time_series_yoy = """
    WITH ticker_price_year_lag as (
        SELECT t1.*, t2.close_price as close_price_year, t2.close_price_indexed as close_price_indexed_year
        FROM ticker_time_series as t1
        JOIN (select *, date(date, '+1 YEAR') as date_lagged
            from ticker_time_series) as t2
        ON t1.ticker = t2.ticker AND t1.date = date_lagged
    ),
    temp_ticker_price_yoy as (
        SELECT ticker, date, close_price / close_price_year - 1 as close_price_yoy, 
            close_price_indexed / close_price_indexed_year - 1 as close_price_indexed_yoy
        FROM ticker_price_year_lag
    ) 
    INSERT OR IGNORE INTO ticker_ts_yoy (ticker, date, close_price_yoy, close_price_indexed_yoy) 
    SELECT ticker, date, close_price_yoy, close_price_indexed_yoy FROM temp_ticker_price_yoy
"""

# query_ticker_metric_yoy = """
#     WITH
#
#     quarterly_ticker_metric_lag as (
#         SELECT q1.*,
#         FROM quarterly_financial_data as q1
#         JOIN (SELECT *, CAST(strftime('%s', datetime(date / 1000000000, 'unixepoch', '+1 YEAR')) AS INTEGER) * 1000000000 as date_lagged
#     )
#
#
# """

recent_metrics_sector_query = """
    SELECT RCM.*, CI.sub_industry FROM ticker_most_recent_metric_data as RCM
    LEFT JOIN (SELECT ticker, sub_industry from company_info) as CI on RCM.ticker = CI.ticker
    WHERE sub_industry = ?
"""

get_table_data_query = """
    SELECT * FROM ? 
"""

get_table_data_within_dates_query = """
    SELECT * FROM ? where date >= ?
"""
