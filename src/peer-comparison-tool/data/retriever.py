"""Class to retrieve and process the finance data gathered from the API"""

import pandas as pd
import yfinance as yf
import os


class RetrieveStockData:
    # Retrieve one stock ticker (info, history etc.) and create a small number of keys metrics with latest yfinance dat
    def __init__(self, stock_ticker: str):
        self._df_quarterly = None
        self._df_balance_sheet = None
        self.stock_info = None
        self.stock_info_key = None
        self.recent_key_metrics = None

        self.data_store = {}
        self.stock_ticker = stock_ticker  # Tickers if we want to look at multiple stock tickers at once
        self.stock = yf.Ticker(self.stock_ticker)
        self.retrieve_balance_sheet()
        self.retrieve_recent_quarterly_financials()
        self.retrieve_stock_info()
        self._retrieve_recent_metrics()

    @property
    def quarterly_finances(self):
        return self._df_quarterly

    @property
    def most_recent_quarterly_finances(self):
        return self._df_quarterly[self._df_quarterly.iloc[:, [0]]]

    @property
    def balance_sheets(self):
        return self._df_balance_sheet

    @property
    def most_recent_balance_sheet(self):
        return self._df_balance_sheet[self._df_balance_sheet.iloc[:, [0]]]

    @property
    def recent_metrics(self):
        return pd.DataFrame(self.recent_key_metrics)

    def _retrieve_recent_metrics(self):
        self.recent_key_metrics = {'market_cap_string': f"""{self.stock.info.get('marketCap'):,}""",  # add commas for each k.
                                   'market_cap': self.stock.info.get("marketCap"),
                                   'price_eps_ratio': round(self.stock.info.get('trailingPE'), 2),
                                   'price_to_book': round(self.stock.info.get('priceToBook'), 2),
                                   'return_on_equity': round(self.stock.info.get("returnOnEquity"), 2),
                                   'debt_to_equity_ratio': round(self.stock.info.get("debtToEquity"), 2),
                                   "EV_EBIDTA": round(self.stock.info.get("enterpriseValue") / self.stock.info.get("ebitda"), 2)
                                   }
        latest_eps = None
        try:
            latest_eps = self.stock.info.get("netIncomeToCommon") / self.stock.info.get("sharesOutstanding")

        except Exception as e:
            pass
        finally:
            self.recent_key_metrics['latest_eps'] = round(latest_eps, 2)

    def retrieve_recent_quarterly_financials(self):
        # might want to process these - but it is columns = dates, rows = key metrics
        self._df_quarterly = self.stock.quarterly_financials

    def retrieve_balance_sheet(self):
        # annual - can be fairly out of date:
        self._df_balance_sheet = self.stock.get_balance_sheet()

    def retrieve_stock_info(self):
        self.stock_info = self.stock.info
        self.stock_info_key = {
            'industry': self.stock_info.get('industry'),
            'sector': self.stock_info.get('sector'),
        }

    def stock_overview_metrics(self):
        stock_overview_map = {
            'ticker': self.stock_ticker,
            'industry': self.stock_info_key.get('industry'),
            'sector': self.stock_info_key.get('sector'),
        }
        stock_overview_map.update(self.recent_key_metrics)
        return stock_overview_map


def write_security_stock_ticker_data() -> None:
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    tables = pd.read_html(url)

    # The S&P 500 table is the first table on the page
    sp500_df = tables[0]

    path = os.path.expanduser('~/Documents/Code/peer-comparison-tool/data/sp500_security_ticker.csv')
    sp500_df.to_csv(path)

    return None


def working_example():
    example_ticker = "AAPL"
    stock_retriever = RetrieveStockData(example_ticker)
    print(f'Key stock metadata info for ticker {example_ticker}: {stock_retriever.stock_info_key}')


if __name__ == '__main__':
    working_example()
    write_security_stock_ticker_data()
