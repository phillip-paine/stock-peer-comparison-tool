import pandas as pd
import numpy as np
import statsmodels.tsa.stattools as st
from statsmodels.tsa.vector_ar.vecm import coint_johansen
from typing import Dict, Any
import yfinance as yf
import plotly.express as px
import os
from typing import List


def test_individual_asset_pairs(tickers: List[str]):
    # Example of not cointegrated, although price moves in line a lot of the time: Visa and Mastercard.
    # Example of cointegrated:
    # This approach does not make sense because of multiple comparisons, but it is useful exploratory/investigative work

    for i, ticker_a in enumerate(tickers):
        for ticker_b in tickers[i+1:]:
            yf_a = yf.Ticker(ticker_a)
            df_a = yf_a.history(period='1y')[['Close']].reset_index()

            yf_b = yf.Ticker(ticker_b)
            df_b = yf_b.history(period='1y')[['Close']].reset_index()
            df_pairs = pd.merge(df_a, df_b, on=['Date'], suffixes=('_a', '_b'), how='inner')
            df_pairs['Close_a_indexed'] = df_pairs['Close_a'] / df_pairs['Close_a'].iloc[0]
            df_pairs['Close_b_indexed'] = df_pairs['Close_b'] / df_pairs['Close_b'].iloc[0]
            cointegrated = cointegration_test(df_pairs['Close_a_indexed'], df_pairs['Close_b_indexed'])
            print(f'{ticker_a} and {ticker_b} cointegrated: {cointegrated}')
            line_fig = px.line(df_pairs, x='Date', y=['Close_a_indexed', 'Close_b_indexed'],
                               title=f'{ticker_a} v. {ticker_b}',
                               labels={'value': 'Value', 'variable': 'Legend'})
            line_fig.show()
    return


def cointegration_test(series_a, series_b, sig_level=0.05):
    if check_stationarity(series_a, sig_level) or check_stationarity(series_b, sig_level):
        return False
    # H0: No Cointegration v. H1: Cointegration
    _, pvalue_coint, _ = st.coint(series_a, series_b)
    # print(f'coint pvalue: {pvalue_coint}')
    return pvalue_coint < sig_level


def check_stationarity(series_a, sig_level=0.05):
    # H0: Non-stationary vs. H1: Stationary/Trend-Stationary
    pvalue_unit_root = st.adfuller(series_a)[1]
    # print(f'Unit root pvalue: {pvalue_unit_root}')
    return pvalue_unit_root < sig_level


def johansen_test(data):
    # Perform Johansen test
    result = coint_johansen(data, det_order=0, k_ar_diff=2)

    # Display results
    print("Eigenvalues (λ):")
    print(result.eig)

    print("\nTrace Statistic:")
    print(result.lr1)

    print("\nCritical Values for Trace Statistic:")
    print(result.cvt)

    print("\nMaximum Eigenvalue Statistic:")
    print(result.lr2)

    print("\nCritical Values for Maximum Eigenvalue Statistic:")
    print(result.cvm)

    # Determine the rank
    rank = 0
    for i in range(len(result.lr1)):
        if result.lr1[i] < result.cvt[i, 1]:  # Using 5% critical value as threshold
            print(f"\nEstimated rank of Π: {i}")
            rank = i
        else:
            print("\nEstimated rank of Π: Full rank")
            rank = i + 1
    return result, rank


def get_cointegrated_ticker_pairs(data, test_result, matrix_rank) -> List[Dict[str, Any]]:

    # Loop through each cointegrating vector
    cointegrated_pairs_data = []
    for r in range(matrix_rank):
        # Extract the r-th cointegrating vector
        coint_vector = test_result.evec[:, r]
        coint_vector = coint_vector / coint_vector[0]  # Normalize

        print(f"\nCointegrating Vector {r+1}: {coint_vector}")

        # Test each pair of series for stationarity using this cointegrating vector
        tickers = [col.split('_')[-1] for col in data.columns]
        # TODO fix the indices, because data fisrt column is Date - could just set to the index infact
        for i in range(data.shape[1]):
            for j in range(i + 1, data.shape[1]):
                # Construct the spread for the pair
                spread = data.iloc[:, i] + coint_vector[j] * data.iloc[:, j]
                adf_test = st.adfuller(spread)

                print(f"Testing Pair: Series {i+1} and Series {j+1}")
                print(f"ADF Test Statistic: {adf_test[0]}, p-value: {adf_test[1]}")

                if adf_test[1] < 0.05:  # Check if the spread is stationary
                    print(f"Series {i+1} and Series {j+1} are cointegrated using Vector {r+1}!")
                    cointegrated_pairs_data.append({
                        'pair': [tickers[i], tickers[j]], 'coint_factor': coint_vector[j],
                        'spread_series': spread, 'rank': r, 'ADF p-value': adf_test[1]
                    })

    # Output the identified cointegrated pairs
    if cointegrated_pairs_data:
        print("\nCointegrated Pairs Identified:")
        for pair in cointegrated_pairs_data:
            print(f"Ticker {pair['pair'][0]} and ticker {pair['pair'][1]}, Cointegrating Factor {round(pair['coint_factor'], 3)}, "
                  f"ADF Test Statistic: {round(pair['ADF p-value'], 3)}")
    else:
        print("\nNo cointegrated pairs identified.")
    return cointegrated_pairs_data


def calculate_spread_statistics(pairs: List[Dict[str, Any]]):
    # FIXME: This currently assumes a normal distribution of the spread series. This may not be true in general.
    for pair_map in pairs:
        mu_spread = pair_map['spread_series'].mean()
        sigma_spread = pair_map['spread_series'].std()
        pair_map.update({
            'mean_spread': mu_spread, 'std_spread': sigma_spread
        })
    return


def create_cointegrated_spread_series(tickers: List[str]) -> List[Dict[str, Any]]:
    # Get Data:
    df_series = pd.DataFrame()
    for ticker in tickers:
        yf_a = yf.Ticker(ticker)
        df_ticker = yf_a.history(period='1y')[['Close']].reset_index()
        df_ticker['log_close'] = np.log(df_ticker['Close'])
        if check_stationarity(df_ticker['log_close']):
            continue

        df_ticker.rename(columns={'log_close': f'log_close_{ticker}'}, inplace=True)
        df_ticker.drop(columns=['Close'], inplace=True)
        if df_series.empty:
            df_series = df_ticker
        else:
            df_series = pd.merge(df_series, df_ticker, left_on='Date', right_on='Date')
    df_series.set_index(keys='Date', inplace=True)
    # drop any columns that will fail:

    # Carry out Johansen test:
    test_output, johansen_matrix_rank = johansen_test(df_series)
    # Get the pairs:

    cointegrated_pairs = get_cointegrated_ticker_pairs(df_series, test_output, johansen_matrix_rank)
    # calculate the spread for each cointegration pair:
    calculate_spread_statistics(cointegrated_pairs)
    return cointegrated_pairs


def spread_alerting(pairs_data: List[Dict[str, Any]]):
    # Check the most recent data from the spread series for a significant deviation from the expected values:
    for pair_map in pairs_data:
        if pair_map['spread_series'].iloc[-1] > (pair_map['mean_spread'] + 2 * pair_map['std_spread']):
            print(f'Long the spread: {pair_map["pair"]} and {pair_map["coint_factor"]}')
        elif pair_map['spread_series'].iloc[-1] < (pair_map['mean_spread'] - 2 * pair_map['std_spread']):
            print(f'Short the spread: {pair_map["pair"]} and {pair_map["coint_factor"]}')
        else:
            print(f'No trading opportunity for {pair_map["pair"]}')
    return


if __name__ == '__main__':
    df_ticker_id = pd.read_csv(os.path.expanduser('~/Documents/Code/peer-comparison-tool/data/sp500_security_ticker.csv'))
    df_ticker_id = df_ticker_id[df_ticker_id['GICS Sub-Industry'] == "Fertilizers & Agricultural Chemicals"]
    ticker_list = df_ticker_id['Symbol'].to_list()
    # test_individual_asset_pairs(ticker_list)
    df_ticker_spread = create_cointegrated_spread_series(ticker_list)
    spread_alerting(df_ticker_spread)
