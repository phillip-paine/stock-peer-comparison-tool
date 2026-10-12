# Stock Peer Comparison Analysis Dashboard

Dashboard application to compare company stock prices and key financial metrics from recent quarterly and annual reports. 
The app provides not just the latest data and key reported and derived financial metrics but also sector and sub-industry peer comparisons. 
Additionally, there are trading and investment strategy tools such as DCF and pairs trading. 

The app is built using dash, data is retrieved from the yfinance library and other web sources when not available and the data is stored on a sqlite database.

Key features of the app:
- The clustering algorithm DBSCAN is used to identify companies that are outliers using features derived from the most recent quarterly report
<img width="1448" alt="Screenshot 2025-01-11 at 10 53 54 PM" src="https://github.com/user-attachments/assets/8f541aeb-1fbf-404a-ac1e-fd0e6c00ab00" />

- Time series data of key metricw from quarterly reports and annual reports
<img width="1448" alt="Screenshot 2025-01-11 at 11 37 00 PM" src="https://github.com/user-attachments/assets/9c45c946-7601-4319-8408-013ec66bcddc" />

- Company performance analysis against sub-industry performance
<img width="1461" alt="Screenshot 2025-01-11 at 11 38 40 PM" src="https://github.com/user-attachments/assets/59350a3e-e7f0-41b4-b3bf-acf7c29cf5a7" />

## Market Conditions page and FRED data

The Market Conditions page shows macro asset moves and news from yfinance, plus four sections backed by
[FRED](https://fred.stlouisfed.org): Rates & Curve (10Y/2Y/3M yields, 2s10s spread, fed funds), Rate Expectations
(the FOMC's median projections and market-leaning proxies), Labor Market and Inflation.

FRED needs a free API key (https://fred.stlouisfed.org/docs/api/api_key.html). Without one the page still works and
those sections say so.

```bash
export FRED_API_KEY=your_key_here          # the shell you run the pipeline from; no .env loading
python -m peer_comparison_tool.main ...    # the pipeline fetches the FRED series once a day
# then restart the dashboard: the data is read once at startup
```

If every series fails (usually a mistyped or not-yet-activated key) the pipeline logs one error pointing at the key;
FRED's own message appears in the warnings above it. The key is redacted from all logs and tracebacks.
Series are defined in `data/transforms/economic_releases.py` (`SERIES_CATALOG`): add one entry to track another.

## And Trading Strategies 

A number of popular and commonly used trading strategies are implemented to identify potential investment opportunities.

### Pairs trading analysis using cointegration and time series anomaly detection

The idea is that cointegrated assets can be used to find long/short positions if a significant deviation is observed in the recent price movements of the spread $asset_1 + b asset_2$.

- Discounted Cash Flow fundamental analysis 
