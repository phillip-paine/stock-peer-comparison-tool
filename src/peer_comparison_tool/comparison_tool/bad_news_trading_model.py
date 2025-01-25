import yfinance as yf
import pandas as pd
import os
from typing import List
from scipy.stats import trim_mean
from constants import DB_PATH, HUGGINGFACE_API_URL, HUGGINGFACE_API_TOKEN
from src.peer_comparison_tool.data.db import initialize_db_connection
import requests
import re
# Could use the huggingfac_hub client as well instead of requests

HUGGINGFACE_HEADER = {"Authorization": f"Bearer {HUGGINGFACE_API_TOKEN}"}


def find_candidate_tickers(df: pd.DataFrame, tickers):
    candidate_tickers = []
    for ticker in tickers:
        try:
            price_series = df[f'Close_{ticker}']
            price_lower_quantile = price_series.quantile(q=0.5)
            price_series_percentiles = price_series.rank(pct=True) * 100
            recent_price_percentiles = trim_mean(price_series_percentiles.iloc[-15:-5], proportiontocut=0.1)
            if (price_series.iloc[-3:].mean() < price_lower_quantile) and (recent_price_percentiles > 90):
                candidate_tickers.append(ticker)
            else:
                price_drop_pct = (price_series.iloc[-3:].mean() / price_series.iloc[-15:-5].mean() - 1)

                if price_drop_pct < -0.01:  # over 1% drop in price
                    candidate_tickers.append(ticker)
        except Exception:
            continue
    return candidate_tickers


def get_ticker_price_data(ticker_list: List[str]):
    df_tickers = pd.DataFrame()
    for ticker in ticker_list:
        yf_ticker = yf.Ticker(ticker)
        try:
            df_ticker = yf_ticker.history(period='1y')[['Close']]
            df_ticker = df_ticker.reset_index()
            df_ticker['Date'] = pd.to_datetime(df_ticker['Date'])
            df_ticker.rename(columns={'Close': f'Close_{ticker}'}, inplace=True)
            if df_tickers.empty:
                df_tickers = df_ticker
            else:
                df_tickers = pd.merge(df_tickers, df_ticker, on='Date')
        except Exception:
            continue
    return df_tickers


def analyse_recent_news(tickers: List[str]):
    tickers_with_bad_news = {}
    message_intro = "Here is the list of news titles to analyse:"
    for ticker in tickers:
        context = f"You are an AI investment analyst and your job is to evaluate the recent news titles for company " \
                  f"ticker {ticker}. Please give a single summary considering the whole list of news titles and give a " \
                  f"rating scale from 1-10 that reflects your opinion of the company given the news titles. " \
                  f"Where 1 = top investment, 5 = average investment, 10 = terrible investment. You should consider if " \
                  f"the news is good or bad for the company in the short and mid-term." \
                  f"Answer format:" \
                  f"Recent news summary: This recent news for company means <opinion of news>." \
                  f"Investment grade: <number from 1-10>." \
                  f"High-level takeaways: <final short note on investing given the recent news titles>"
        yf_ticker = yf.Ticker(ticker)
        ticker_news = yf_ticker.get_news()
        # todo use chatgpt to evaluate badness of the news
        input_message = context + "\n\n" + message_intro + "\n" + "\n".join([news['title'] for news in ticker_news])
        huggingface_payload = {
            "inputs": input_message,
        }
        response = requests.post(HUGGINGFACE_API_URL, headers=HUGGINGFACE_HEADER, json=huggingface_payload)
        response = response.json()
        # parse the response:
        response = response[0]['generated_text']
        analysis_output = response.split("Recent news summary:")[-1]
        summary_output = analysis_output.split("Investment")[0].strip()
        investment_grade = analysis_output.split("Investment grade:")[1].split("High-level")[0].strip()
        grade_score = float(re.sub(r'[^\w\s]', '', investment_grade[:3]))
        grade_score = grade_score if grade_score < 11 else grade_score/10
        analysis_breakdown = {
            'summary': summary_output,
            'investment grade': grade_score
        }
        tickers_with_bad_news[ticker] = analysis_breakdown

    return tickers_with_bad_news


def find_bad_news_price_drops(tickers: List[str]):

    sql_conn = initialize_db_connection(DB_PATH)
    sql_query_market_cap = """SELECT ticker, market_cap from ticker_most_recent_metric_data"""
    df_tickers = pd.read_sql_query(sql_query_market_cap, sql_conn)
    df_tickers.sort_values(by='market_cap', ascending=False, inplace=True)
    big_tickers = df_tickers.loc[:20, "ticker"].to_list()
    df_price = get_ticker_price_data(big_tickers)
    candidate_price_tickers = find_candidate_tickers(df_price, big_tickers)

    candidate_investments = analyse_recent_news(candidate_price_tickers)  # TODO needs genAI

    return candidate_price_tickers


if __name__ == '__main__':
    df_ticker_id = pd.read_csv(os.path.expanduser('~/Documents/Code/peer-comparison-tool/data/sp500_security_ticker.csv'))
    # Testing code:
    # apple_ticker = yf.Ticker("Aapl")
    # apple_news = apple_ticker.get_news()  # returns the latest 8 stories?
    # meta_ticker = yf.Ticker("meta")
    # meta_news = meta_ticker.get_news()  # returns the latest 8 stories?
    #
    # oil_ticker = yf.Ticker("oil")
    # oil_news = oil_ticker.get_news()  # returns the latest 8 stories?
    # oil_titles = [news['title'] for news in oil_news]
    # df_ticker_id = df_ticker_id[df_ticker_id['GICS Sector'] == "Industrials"]
    tickers = list(df_ticker_id['Symbol'].unique())
    candidates = find_bad_news_price_drops(tickers)

    a = 1
