query_industry_price_aggregation = """
    WITH ticker_sector_price as (
        SELECT * FROM ticker_time_series as TTS 
        JOIN (SELECT * from company_info) as CI ON TTS.ticker = CI.ticker
    ),
    industry_aggregate_price as (
        SELECT industry, date, sum(close_price) as industry_close_price, sum(close_price_indexed) as industry_close_price_indexed
        FROM ticker_sector_price
        GROUP BY industry, date
    )
    INSERT INTO industry_time_series (industry, date, industry_close_price, industry_close_price_indexed) 
    SELECT * from industry_aggregate_price WHERE date >= ?;
"""

query_industry_price_yoy = """
    
"""

query_industry_aggregation = """
    WITH quarterly_sector_financials as (
        SELECT * FROM quarterly_financial_data as QFD JOIN (SELECT ticker, .. FROM company_info) as CI on QFD.ticker = CI.ticker
    )
    SELECT * FROM xyz JOIN quarterly_sector_financials as QFD on xyz.a = QFD.a where xyz.date > (date) 
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
    INSERT INTO ticker_ts_yoy (ticker, date, close_price_yoy, close_price_indexed_yoy) 
    SELECT ticker, date, close_price_yoy, close_price_indexed_yoy FROM temp_ticker_price_yoy
"""

recent_metrics_sector_query = """
    SELECT RCM.*, CI.sub_industry FROM ticker_most_recent_metric_data as RCM
    LEFT JOIN (SELECT ticker, sub_industry from company_info) as CI on RCM.ticker = CI.ticker
    WHERE sub_industry = ?
"""
