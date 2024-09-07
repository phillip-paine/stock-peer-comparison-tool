"""Class to retrieve and process the finance data gathered from the API"""

import pandas as pd
import numpy as np
import yfinance as yf
import os


class DataRetrievalError(Exception):
    """Custom exception for data retrieval failures."""
    pass


class RetrieveStockData:
    # Retrieve one stock ticker (info, history etc.) and create a small number of keys metrics with latest yfinance dat
    def __init__(self, stock_ticker: str):
        self._df_quarterly = None
        self._df_balance_sheet = None
        self._df_stock_history = None
        self._df_cashflow = None
        self.stock_info = None
        self.stock_info_key = None
        self.recent_key_metrics = None

        self.data_store = {}
        self.stock_level_data_store = {}
        self.qfin_columns = ['Basic EPS', 'Operating Income', 'Total Revenue', 'Gross Profit', 'Net Income', 'EBITDA']
        self.cashflow_columns = ['Free Cash Flow', 'Operating Cash Flow', 'Capital Expenditure']
        self.stock_ticker = stock_ticker  # Tickers if we want to look at multiple stock tickers at once
        self.stock = yf.Ticker(self.stock_ticker)
        self.stock_check_then_retrieve_data()
        self.retrieve_stock_info()
        self._retrieve_recent_metrics()

    def stock_check_then_retrieve_data(self):
        try:
            self.retrieve_balance_sheet()
            self.retrieve_recent_quarterly_financials()
            self.retrieve_cashflow_data()

        except DataRetrievalError as e:
            print(f"Error {e}")

    @property
    def quarterly_finances(self):
        if self._df_quarterly is None:
            self.retrieve_recent_quarterly_financials()

        return self._df_quarterly

    @property
    def most_recent_quarterly_finances(self):
        return self.quarterly_finances[self.quarterly_finances.iloc[:, [0]]]

    @property
    def balance_sheets(self):
        return self._df_balance_sheet

    @property
    def most_recent_balance_sheet(self):
        return self._df_balance_sheet[self._df_balance_sheet.iloc[:, [0]]]

    @property
    def recent_metrics(self):
        return pd.DataFrame(self.recent_key_metrics)

    @property
    def stock_overview_map(self):
        return self._stock_overview_map()

    @staticmethod
    def safe_round(value, decimals=2):
        return round(value, decimals) if value is not None else None

    @staticmethod
    def safe_divide(numerator, denominator):
        return numerator / denominator if denominator is not None and numerator is not None and denominator > 0 else None

    @staticmethod
    def safe_string_format(value):
        return f"""{value:,}""" if value is not None else None

    def fetch_time_series_data(self):
        self._df_stock_history = self.stock.history(period="2y")

    def _retrieve_recent_metrics(self):
        self.recent_key_metrics = {'market_cap_string': self.safe_string_format(self.stock.info.get('marketCap')),  # add commas for each k.
                                   'market_cap': self.stock.info.get("marketCap"),
                                   'price_eps_ratio': self.safe_round(self.stock.info.get('trailingPE'), 2),
                                   'price_to_book': self.safe_round(self.stock.info.get('priceToBook'), 2),
                                   'return_on_equity': self.safe_round(self.stock.info.get("returnOnEquity"), 2),
                                   'debt_to_equity_ratio': self.safe_round(self.stock.info.get("debtToEquity"), 2),
                                   "enterprise_value": self.safe_round(self.stock.info.get("enterpriseValue"), 2),
                                   "profit_margin": self.safe_round(self.stock.info.get("profitMargins"), 2),
                                   "enterpriseToEbitda": self.safe_round(self.stock.info.get("enterpriseToEbitda"), 2),
                                   }
        latest_eps = None
        try:
            latest_eps = self.stock.info.get("netIncomeToCommon") / self.stock.info.get("sharesOutstanding")

        except Exception as e:
            pass
        finally:
            self.recent_key_metrics['latest_eps'] = self.safe_round(latest_eps, 2)

    def retrieve_recent_quarterly_financials(self):
        # might want to process these - but it is columns = dates, rows = key metrics
        self._df_quarterly = self.stock.quarterly_financials

    def get_quarterly_financials_app_data(self):
        try:
            df = self.quarterly_finances.loc[self.qfin_columns]
        except KeyError as e:
            print(f"{e}: No quarterly financial statements for {self.stock_ticker}")
            return pd.DataFrame()
        df = df.astype(float)
        df.fillna(value=0.0, inplace=True)
        # transform rows to columns and columns to rows:
        df = df.transpose()
        df['Gross Margin'] = np.where(df['Total Revenue'] > 0, df['Gross Profit'] / df['Total Revenue'] * 100, 0)
        df['Operating Margin'] = np.where(df['Total Revenue'] > 0, df['Operating Income'] / df['Total Revenue'] * 100, 0)
        df['Net Margin'] = np.where(df['Total Revenue'] > 0, df['Net Income'] / df['Total Revenue'] * 100, 0)
        df['EBITDA Margin'] = np.where(df['Total Revenue'] > 0, df['EBITDA'] / df['Total Revenue'] * 100, 0)
        df.drop(columns=['Total Revenue', 'Gross Profit', 'EBITDA'], inplace=True)
        # todo standardise the dates into year-quarter because they are not always the same date here
        return df

    def retrieve_balance_sheet(self):
        # annual - can be fairly out of date:
        self._df_balance_sheet = self.stock.get_balance_sheet()

    def get_balance_sheet_app_data(self):
        df = self.balance_sheets
        df = df.astype(float)
        df.fillna(value=0.0, inplace=True)
        df = df.transpose()
        bs_cols = ['OrdinarySharesNumber', 'StockholdersEquity', 'TotalLiabilitiesNetMinorityInterest', 'CurrentAssets']
        try:
            df = df[bs_cols].copy()
        except KeyError as e:
            print(f"{e}: No balance sheet data for {self.stock_ticker}")
            return pd.DataFrame()
        # processing and creating new insight columns:
        if 'Inventory' in df.columns:
            df['Quick Ratio'] = (df['CurrentAssets'] - df['Inventory']) / df['TotalLiabilitiesNetMinorityInterest']
        else:
            df['Quick Ratio'] = df['CurrentAssets'] / df['TotalLiabilitiesNetMinorityInterest']

        df['Equity Ratio'] = (df['CurrentAssets'] - df['TotalLiabilitiesNetMinorityInterest']) / df['OrdinarySharesNumber']
        df['Debt-to-Equity Ratio'] = df['TotalLiabilitiesNetMinorityInterest'] / df['StockholdersEquity']
        return df

    def get_stock_level_data(self):
        stock_history = self.stock.history(period='1y')
        stock_history.reset_index(inplace=True)
        self.stock_level_data_store['stock_price_data'] = stock_history[['Date', 'Close']]
        # Create the normalised stock price data:
        stock_history_normalised = stock_history[['Date', 'Close']].copy()
        stock_history_normalised['Close'] = stock_history_normalised['Close'] / stock_history_normalised['Close'].iloc[0] * 100
        self.stock_level_data_store['stock_price_normalised_data'] = stock_history_normalised

        self.stock_level_data_store['short_ratio'] = self.stock.info['shortRatio']
        income_statement = self.stock.income_stmt
        income_statement_rows = ['Total Revenue', 'Net Income Continuous Operations', 'Basic EPS']
        income_statement_cols = [c for c in income_statement.columns][:2]
        for row in income_statement_rows:
            # dates read left to right:
            self.stock_level_data_store[f"{row}_yoy"] = round((income_statement.loc[row, income_statement_cols[0]] / income_statement.loc[row, income_statement_cols[1]]) - 1, 2) * 100
        net_margin_this_year = (income_statement.loc['Total Revenue', income_statement_cols[0]] - income_statement.loc['Total Expenses', income_statement_cols[0]]) / income_statement.loc['Total Expenses', income_statement_cols[0]] * 100
        net_margin_last_year = (income_statement.loc['Total Revenue', income_statement_cols[1]] - income_statement.loc['Total Expenses', income_statement_cols[1]]) / income_statement.loc['Total Expenses', income_statement_cols[1]] * 100
        self.stock_level_data_store['net_margin_yoy'] = round(net_margin_this_year / net_margin_last_year - 1, 2) * 100
        self.stock_level_data_store['stock_price_yoy'] = round(stock_history['Close'].iloc[-1] / stock_history['Close'].iloc[0] - 1, 2) * 100
        return self.stock_level_data_store

    def retrieve_cashflow_data(self):
        self._df_cashflow = self.stock.cashflow

    def get_cashflow_data(self):
        df = self._df_cashflow.transpose()
        df.sort_index(inplace=True)
        return df[self.cashflow_columns]

    def retrieve_stock_info(self):
        self.stock_info = self.stock.info
        self.stock_info_key = {
            'industry': self.stock_info.get('industry'),
            'sector': self.stock_info.get('sector'),
        }

    def _stock_overview_map(self):
        stock_overview_map = {
            'ticker': self.stock_ticker,
            'industry': self.stock_info_key.get('industry'),
            'sector': self.stock_info_key.get('sector'),
        }
        return stock_overview_map

    def add_stock_overview_metrics_to_key_metrics(self):
        stock_key_metrics_info = self._stock_overview_map()
        stock_key_metrics_info.update(self.recent_key_metrics)
        return stock_key_metrics_info


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
