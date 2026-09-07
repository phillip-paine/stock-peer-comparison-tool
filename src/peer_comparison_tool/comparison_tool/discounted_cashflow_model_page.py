"""
Discounted cash flow (DCF) scenario page.

Pure calculation logic lives in `data.transforms.dcf` (same pattern as
`pairs_trading.py` -- extracted so it's testable without a Dash app). This
file is layout + callback wiring only; see that module's docstring for the
two valuation bugs found and fixed in the actual math.

Bugs found and fixed here, in the wiring itself:

- `list(latest_ev_data['ticker'].unique)` -- missing `()` on `.unique`, and
  separately, `latest_ev_data` (as loaded by `data_loader.py`) is indexed
  by ticker rather than having a `ticker` column, so this line couldn't
  have worked either way. The dropdown is now built from `cashflow_map`
  instead -- the actual thing that determines whether a DCF can be run for
  a given ticker (you need cash flow history to forecast from).
- `cashflow_map.get(ticker).reset_index(...)` ran *before* the
  `if df_cashflow is None:` check meant to catch a missing ticker -- so
  that check could never actually fire; the crash would already have
  happened on the line above it. Reordered.
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import dcc, html

from src.peer_comparison_tool.data.transforms.dcf import compute_dcf_scenarios

from .styles import colors

_EMPTY_FIGURE = px.line(title="Select a ticker and click \"Calculate DCF\"")


def get_discounted_cashflow_model_page_layout(cashflow_map: dict[str, pd.DataFrame]) -> dbc.Container:
    ticker_options = sorted(cashflow_map.keys())
    default_ticker = ticker_options[0] if ticker_options else None

    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Discounted Cash Flow Model", style={'color': colors['text'], 'textAlign': 'center'}), width=10,
                className="mb-4"),
            dbc.Col(dbc.Button("Return to Home", id="back-to-home", color="primary", className="mb-3"), width=2)
        ], align='center'
        ),

        dbc.Row([
            dbc.Col([
                html.Label("Select Company:", style={'color': colors['text']}),
                dcc.Dropdown(
                    id='company-dropdown',
                    options=[{'label': ticker, 'value': ticker} for ticker in ticker_options],
                    value=default_ticker,
                    multi=False,
                    searchable=True,
                    placeholder="Select ticker...",
                    style={'marginBottom': '15px'}
                )
            ], width=6),

            dbc.Col([
                html.H4('Forecasting Inputs'),  # Main heading

                dbc.Row([
                    dbc.Col([
                        html.H5('Growth Rate (%)'),  # Sub-heading for Growth Rate
                        dbc.InputGroup([
                            dcc.Input(id='growth-rate-input', type='number', value=5)
                        ]),
                    ], width=3),
                    dbc.Col([
                        html.H5('Discount Rate (%)'),  # Sub-heading for Discount Rate
                        dbc.InputGroup([
                            dcc.Input(id='discount-rate-input', type='number', value=10)
                        ]),
                    ], width=3),
                    dbc.Col([
                        html.H5('Terminal Rate (%)'),  # Sub-heading for Terminal Rate
                        dbc.InputGroup([
                            dcc.Input(id='terminal-rate-input', type='number', value=8)
                        ]),
                    ], width=3)
                ]),

                # Calculate DCF Button
                html.Button("Calculate DCF", id="calculate-dcf-button", n_clicks=0, style={'marginTop': '20px'}),

            ])
        ]),

        dbc.Row(
            dbc.Col(
                dbc.Alert(
                    "Illustrative only, not investment advice. A discounted cash flow model is highly sensitive "
                    "to the growth/discount/terminal rate assumptions above, and the terminal value (usually most "
                    "of the total) depends on the discount rate staying above the terminal growth rate -- if a "
                    "scenario below shows \"invalid inputs\", that scenario's rates violate that.",
                    color="warning", style={"margin": "15px 0"},
                ), width=12,
            )
        ),

        # Plot Cashflow and DCF over time and show discounted cash flow values:
        dbc.Row([
            dbc.Col([
                html.H5("Present Value Cash Flow Growth"),
                dbc.Card([
                    dcc.Graph(id="cash-flow-growth-plot", figure=_EMPTY_FIGURE)
                ], style={'backgroundColor': colors['background']}),
            ], width=8),
            dbc.Col([
                html.H5("EV -to- Discounted Cash Flow:"),
                # EV Value
                dbc.Card([
                    dbc.CardHeader("Enterprise Value (EV)"),
                    dbc.CardBody([
                        html.H4(id='ev-value', className='card-title'),
                        html.P("Current market-based value of the company", className='card-text')
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),
                # Percentage Error for each scenario
                dbc.Card([
                    dbc.CardHeader("Scenario Percentage Error"),
                    dbc.CardBody([
                        # Low scenario percentage error
                        dbc.Row([
                            dbc.Col(html.H5("Low (Bear):"), width=4),
                            dbc.Col(html.H5(id="bear-percentage-error"), width=8),
                        ], className="mb-2"),
                        # Mid scenario percentage error
                        dbc.Row([
                            dbc.Col(html.H5("Mid (Base):"), width=4),
                            dbc.Col(html.H5(id="base-percentage-error"), width=8),
                        ], className="mb-2"),
                        # High scenario percentage error
                        dbc.Row([
                            dbc.Col(html.H5("High (Bull):"), width=4),
                            dbc.Col(html.H5(id="bull-percentage-error"), width=8),
                        ]),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'})
            ], width=4)
        ])

    ], fluid=True, style={'backgroundColor': colors['background']})


def register_discounted_cashflow_model_page_callbacks(
    app: dash.Dash, cashflow_map: dict[str, pd.DataFrame], latest_ev: pd.DataFrame
) -> None:
    @app.callback(
        dash.dependencies.Output('ev-value', 'children'),
        dash.dependencies.Output('base-percentage-error', 'children'),
        dash.dependencies.Output('bear-percentage-error', 'children'),
        dash.dependencies.Output('bull-percentage-error', 'children'),
        dash.dependencies.Output('base-percentage-error', 'style'),
        dash.dependencies.Output('bear-percentage-error', 'style'),
        dash.dependencies.Output('bull-percentage-error', 'style'),
        dash.dependencies.Output("cash-flow-growth-plot", "figure"),
        dash.dependencies.Input('calculate-dcf-button', 'n_clicks'),
        dash.dependencies.State('company-dropdown', 'value'),
        dash.dependencies.State('growth-rate-input', 'value'),
        dash.dependencies.State('terminal-rate-input', 'value'),
        dash.dependencies.State('discount-rate-input', 'value')
    )
    def calculate_dcf(n_clicks, ticker, growth_rate, terminal_rate, discount_rate):
        empty_style = {"color": colors["text"]}
        empty_result = ("", "", "", "", empty_style, empty_style, empty_style, _EMPTY_FIGURE)

        if not n_clicks or not ticker:
            return empty_result

        df_cashflow = cashflow_map.get(ticker)
        if df_cashflow is None:
            return "No cash flow data for this ticker", "", "", "", empty_style, empty_style, empty_style, _EMPTY_FIGURE
        df_cashflow = df_cashflow.reset_index(names=['date'])

        start_date = df_cashflow['date'].iloc[-1] + pd.DateOffset(years=1)
        latest_free_cashflow = df_cashflow['Free Cash Flow'].iloc[-1]  # latest value, frame is sorted ascending

        scenarios = compute_dcf_scenarios(latest_free_cashflow, growth_rate, discount_rate, terminal_rate, start_date)

        if "error" in scenarios["base"]:
            message = f"Base scenario: {scenarios['base']['error']}"
            return message, "", "", "", empty_style, empty_style, empty_style, _EMPTY_FIGURE

        forecast_frames = [df_cashflow[['date', 'Free Cash Flow']]]
        for name, rename_to in [("base", "Discounted Forecast Free Cash Flow"),
                                 ("bear", "Bear Discounted Forecast FCF"),
                                 ("bull", "Bull Discounted Forecast FCF")]:
            scenario = scenarios[name]
            if "error" in scenario:
                continue
            frame = scenario["cashflow_df"].rename(columns={"Discounted Forecast Free Cash Flow": rename_to})
            forecast_frames.append(frame)

        df_ts_plot = pd.concat(forecast_frames)
        df_ts_plot['date'] = pd.to_datetime(df_ts_plot['date'])
        df_ts_plot['year'] = df_ts_plot['date'].dt.year.astype(str)
        value_cols = [c for c in ['Free Cash Flow', 'Discounted Forecast Free Cash Flow',
                                   'Bear Discounted Forecast FCF', 'Bull Discounted Forecast FCF']
                      if c in df_ts_plot.columns]
        df_ts_plot = df_ts_plot.melt(id_vars='year', value_vars=value_cols,
                                      var_name='Cash Flow Type', value_name='Value')
        cashflow_ts_plot = px.line(df_ts_plot, x='year', y='Value', color='Cash Flow Type',
                                    title="Historical Cash Flow and Discounted Forecast Cash Flow Growth Over Time")

        ev_value = latest_ev.loc[ticker, 'enterprise_value']
        ev_value_str = f"{int(ev_value / 1_000_000)} mm"

        def percentage_error_and_style(scenario_name):
            scenario = scenarios[scenario_name]
            if "error" in scenario:
                return "n/a (invalid inputs)", empty_style
            pct_error = round((scenario['dcf_value'] - ev_value) / ev_value * 100, 2)
            return f"{pct_error}", {"color": determine_color(pct_error)}

        base_text, base_style = percentage_error_and_style("base")
        bear_text, bear_style = percentage_error_and_style("bear")
        bull_text, bull_style = percentage_error_and_style("bull")

        return ev_value_str, base_text, bear_text, bull_text, base_style, bear_style, bull_style, cashflow_ts_plot


def determine_color(value):
    if value < -10:
        return "red"
    elif value > 10:
        return "green"
    else:
        return "white"
