import dash
from dash import html, dash_table, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import os
import plotly.graph_objects as go
from .styles import colors
from .constants import DOWNLOAD_DIR
from dateutil.relativedelta import relativedelta

import pandas as pd

from .layout import create_container, create_header
CF_FUTURE_YEARS = 5


def get_discounted_cashflow_model_page_layout(data, latest_ev_data):
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
                    options=[{'label': ticker, 'value': ticker} for ticker in list(data.keys())],
                    value=list(data.keys())[0],  # Default selection - jut pick first ticker
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

        # Plot Cashflow and DCF over time and show discounted cash flow values:
        dbc.Row([
            dbc.Col([
                html.H5("Present Value Cash Flow Growth"),
                dbc.Card([
                    dcc.Graph(id="cash-flow-growth-plot")
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


def register_discounted_cashflow_model_page_callbacks(app, cashflow_map, latest_ev):
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
        if n_clicks is None:
            return ""

        # Fetch financial data and calculate DCF
        df_cashflow = cashflow_map.get(ticker).reset_index(names=['date'])
        if df_cashflow is None:
            return ""

        # Now we want the three scenarios:
        # Example calculation (simplified)
        start_date = df_cashflow['date'].iloc[-1] + pd.DateOffset(years=1)
        latest_free_cashflow = df_cashflow['Free Cash Flow'].iloc[-1]  # we want the latest value as ordered

        df_forecast_cf, forecast_discounted_cf, forecast_discounted_terminal_value = \
            create_forecast_cashflow_dataframe(latest_free_cashflow, growth_rate, discount_rate, terminal_rate, start_date)
        df_bear_forecast_cf, low_forecast_discounted_cf, low_forecast_discounted_terminal_value = \
            create_forecast_cashflow_dataframe(latest_free_cashflow, growth_rate*0.8, discount_rate*1.1, terminal_rate*0.8, start_date)
        df_bear_forecast_cf.rename(columns={'Discounted Forecast Free Cash Flow': 'Bear Discounted Forecast FCF'}, inplace=True)
        df_bull_forecast_cf, high_forecast_discounted_cf, high_forecast_discounted_terminal_value = \
            create_forecast_cashflow_dataframe(latest_free_cashflow, growth_rate*1.2, discount_rate*0.9, terminal_rate*1.2, start_date)
        df_bull_forecast_cf.rename(columns={'Discounted Forecast Free Cash Flow': 'Bull Discounted Forecast FCF'}, inplace=True)

        df_ts_plot = pd.concat([df_cashflow[['date', 'Free Cash Flow']], df_forecast_cf,
                                df_bear_forecast_cf, df_bull_forecast_cf])

        df_ts_plot['year'] = df_ts_plot['date'].dt.year.astype(str)
        df_ts_plot = df_ts_plot.melt(id_vars='year', value_vars=['Free Cash Flow', 'Discounted Forecast Free Cash Flow',
                                                                 'Bear Discounted Forecast FCF', 'Bull Discounted Forecast FCF'],
                                     var_name='Cash Flow Type', value_name='Value')
        # Now lets add the calculated free cash flow values forecast:
        cashflow_ts_plot = px.line(df_ts_plot, x='year', y='Value', color='Cash Flow Type',
                                   title="Historical Cash Flow and Discounted Forecast Cash Flow Growth Over Time")

        # And calculate the DCF:
        base_dcf_value = int(forecast_discounted_cf + forecast_discounted_terminal_value)
        low_dcf_value = int(low_forecast_discounted_cf + forecast_discounted_terminal_value)
        high_dcf_value = int(high_forecast_discounted_cf + forecast_discounted_terminal_value)
        # dcf_value_str = f"{int((forecast_discounted_cf + forecast_discounted_terminal_value) / 1_000_000)} mm"

        ev_value_str = f"{int(latest_ev.loc[ticker, 'enterprise_value'] / 1_000_000)} mm"
        ev_value = latest_ev.loc[ticker, 'enterprise_value']

        base_percentage_error = round((base_dcf_value - ev_value) / ev_value * 100, 2)
        low_percentage_error = round((low_dcf_value - ev_value) / ev_value * 100, 2)
        high_percentage_error = round((high_dcf_value - ev_value) / ev_value * 100, 2)

        bear_colour = {"color": determine_color(low_percentage_error)}
        bull_colour = {"color": determine_color(high_percentage_error)}
        mid_colour = {"color": determine_color(base_percentage_error)}

        return ev_value_str, f"{base_percentage_error}", f"{low_percentage_error}", f"{high_percentage_error}", \
            mid_colour, bear_colour, bull_colour, cashflow_ts_plot


def create_forecast_cashflow_dataframe(latest_free_cashflow, growth_rate, discount_rate, terminal_rate, calculation_date):
    future_cashflows = []
    discounted_future_cashflows = []
    for year in range(1, CF_FUTURE_YEARS + 1):
        future_cashflows.append(latest_free_cashflow*((1 + growth_rate/100) ** year))
        discounted_future_cashflows.append(future_cashflows[-1] / ((1 + discount_rate / 100) ** year))
    terminal_value = future_cashflows[-1] * (1 + terminal_rate / 100) / (discount_rate - terminal_rate)
    discounted_terminal_value = terminal_value / ((1 + discount_rate / 100) ** CF_FUTURE_YEARS)
    total_discounted_future_cashflows = sum(discounted_future_cashflows)

    # Cash flow ts: add the forecast cashflow to the historical cashflows

    df_future_cashflow = pd.DataFrame({"date": pd.date_range(calculation_date.strftime("%Y-%m-%d"), periods=CF_FUTURE_YEARS, freq='Y'),
                                       "Discounted Forecast Free Cash Flow": discounted_future_cashflows})
    return df_future_cashflow, total_discounted_future_cashflows, discounted_terminal_value


def determine_color(value):
    if value < -10:
        return "red"
    elif value > 10:
        return "green"
    else:
        return "white"
