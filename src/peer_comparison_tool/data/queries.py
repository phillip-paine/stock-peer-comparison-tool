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
    select * from industry_aggregate_price limit 1;
"""

query_industry_price_yoy = """
    
"""

query_industry_aggregation = """
    WITH quarterly_sector_financials as (
        SELECT * FROM quarterly_financial_data as QFD JOIN (SELECT ticker, sub_industry FROM company_info) as CI on QFD.ticker = CI.ticker
    )
    SELECT * FROM quarterly_sector_financials JOIN quarterly_sector_financials as QFD on xyz.a = QFD.a where xyz.date > (date) 
"""

query_ticker_yoy = """
    WITH ticker_price_year_lag as (
        SELECT t1.*, t2.close_price as close_price_year, t2.close_price_indexed as close_price_indexed_year
        FROM ticker_time_series as t1
        JOIN ticker_time_series as t2
        ON t1.ticker = t2.ticker AND t1.date = DATE(t2.date, '+1 YEAR')
    ),
    temp_ticker_price_yoy as (
        SELECT ticker, date, close_price / close_price_year - 1 as close_price_yoy, 
            close_price_indexed / close_price_indexed_year - 1 as close_price_indexed_yoy
        FROM ticker_price_year_lag
    ) 
    INSERT OR IGNORE INTO ticker_ts_yoy (ticker, date, close_price_yoy, close_price_indexed_yoy) 
    SELECT ticker, date, close_price_yoy, close_price_indexed_yoy FROM temp_ticker_price_yoy
"""

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
