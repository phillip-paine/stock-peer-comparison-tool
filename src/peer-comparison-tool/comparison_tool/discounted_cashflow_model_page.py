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
                    id='ticker-dropdown',
                    options=[{'label': ticker, 'value': ticker} for ticker in list(data.keys())],
                    value=list(data.keys())[0],  # Default selection - jut pick first ticker
                    multi=False,
                    searchable=True,
                    placeholder="Select ticker...",
                    style={'marginBottom': '15px'}
                )
            ], width=6),

            dbc.Col([
                html.H4('Forecasting Inputs', className='mb-3'),  # Main heading

                dbc.Row([
                    dbc.Col([
                        html.H5('Growth Rate (%)', className='mt-4'),  # Sub-heading for Growth Rate
                        dcc.Input(id='growth-rate-input', type='number', value=5),
                    ], width=2),
                    dbc.Col([
                        html.H5('Discount Rate (%)', className='mt-4'),  # Sub-heading for Discount Rate
                        dcc.Input(id='discount-rate-input', type='number', value=10),
                    ], width=2),
                    dbc.Col([
                        html.H5('Terminal Rate (%)', className='mt-4'),  # Sub-heading for Terminal Rate
                        dcc.Input(id='discount-rate-input', type='number', value=10),
                    ], width=2)
                ]),

                # Calculate DCF Button
                html.Button("Calculate DCF", id="calculate-dcf-button", n_clicks=0, style={'marginTop': '20px'}),

            ], width=6)
        ]),

        # Plot Cashflow and DCF over time and show discounted cash flow values:
        dbc.Row([
            dbc.Col([
                html.H5("Cash Flow Growth Over Time"),
                dcc.Graph(id="cash-flow-growth-plot"),
            ], width=8),
            dbc.Col([
                html.H5("Discounted Cash Flow:"),

                dbc.Card([
                    dbc.CardHeader("Calculated DCF Value"),
                    dbc.CardBody([
                        html.H4(id='dcf-result', className='card-title'),
                        html.P("This is the present value of projected cash flows", className='card-text')
                    ]),
                ]),

                # EV Value
                dbc.Card([
                    dbc.CardHeader("Enterprise Value (EV)"),
                    dbc.CardBody([
                        html.H4(id='ev-value', className='card-title'),
                        html.P("Current market-based value of the company", className='card-text')
                    ]),
                ]),

                # Percentage Error
                dbc.Card([
                    dbc.CardHeader("Percentage Error"),
                    dbc.CardBody([
                        html.H4(id='percentage-error', className='card-title'),
                        html.P("Error between DCF value and EV", className='card-text')
                    ]),
                ]),
            ], width=4)
        ])

    ], fluid=True, style={'backgroundColor': colors['background']})


def register_discounted_cashflow_model_page_callbacks(app, cashflow_map, latest_ev):
    @app.callback(
        dash.dependencies.Output('dcf-result', 'children'),
        dash.dependencies.Output('ev-value', 'children'),
        dash.dependencies.Output('percentage-error', 'children'),
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
        df_cashflow = cashflow_map.get(ticker)
        if df_cashflow is None:
            return ""

        # Example calculation (simplified)
        latest_free_cashflow = df_cashflow.loc['Free Cash Flow'].values[-1]  # we want the latest value as ordered
        future_cashflows = []
        discounted_future_cashflows = []
        for year in range(1, CF_FUTURE_YEARS + 1):
            future_cashflows.append(latest_free_cashflow*((1 + growth_rate/100) ** year))
            discounted_future_cashflows.append(future_cashflows[-1] / ((1 + discount_rate / 100) ** year))
        terminal_value = future_cashflows[-1] * (1 + terminal_rate / 100) / (discount_rate - terminal_rate)
        discounted_terminal_value = terminal_value / ((1 + discount_rate / 100) ** CF_FUTURE_YEARS)

        # Cash flow ts: add the forecast cashflow to the historical cashflows
        start_date = df_cashflow['date'] + relativedelta(years=1)
        df_future_cashflow = pd.DataFrame({"date": pd.date_range(start_date, periods=CF_FUTURE_YEARS, freq='Y'),
                                           "Free Cash Flow": discounted_future_cashflows})
        df_ts_plot = pd.concat([df_cashflow[['date', 'Free Cash Flow']], df_future_cashflow])

        df_ts_plot['year'] = df_ts_plot.index.dt.year.astype(str)
        # Now lets add the calculated free cash flow values forecast:
        cashflow_ts_plot = px.line(df_ts_plot, x='year', y='Free Cash Flow',
                                   title="Present Discounted Cash Flow Growth Over Time")

        # And calculate the DCF:
        dcf_value = sum(discounted_future_cashflows) + discounted_terminal_value

        ev_value = latest_ev.loc[ticker, "enterprise_value"]

        percentage_error = (dcf_value - ev_value) / ev_value

        return dcf_value, ev_value, percentage_error, cashflow_ts_plot
