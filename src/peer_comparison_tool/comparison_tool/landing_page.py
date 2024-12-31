from typing import Dict, Any

import pandas as pd
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
from .layout import create_container, create_header
from .styles import colors


# Create card from header + content
def create_card(title, content):
    return dbc.Card(
        [
            dbc.CardHeader(title),
            dbc.CardBody(content),
        ],
        className="mb-4",
    )


# Function to get the layout for the Landing Page
def get_landing_page_layout_v2(economic_data: pd.DataFrame):
    app_layout = html.Div([
        dcc.Store(id='dummy-store', data='initial'),  # Dummy store to trigger the callback
        # Header
        dbc.NavbarSimple(
            brand="Financial Dashboard",
            color=colors['background'],
            dark=True,
            className="mb-4",
        ),

        dbc.Row([

            # Left-hand navigation (1/4 page width)
            dbc.Col(
                dbc.Nav(
                    [
                        dbc.NavLink("Home", href="/", active="exact"),
                        dbc.NavLink("Industry Comparison", href="/comparison", active="exact"),
                        dbc.NavLink("Quarterly Reports", href="/quarterly-report-ts-data", active="exact"),
                        dbc.NavLink("Yearly Balance Statememt", href="/balance-sheet-report-ts-data", active="exact"),
                        dbc.NavLink("Company Overviews", href="/company-stock-overview-data", active="exact"),
                        # dbc.NavLink("Discounted Cashflow Model", href="/company-discounted-cashflow-calculation", active="exact"),
                    ],
                    vertical=True,
                    pills=True,
                ), width=2
            ),

            # Main content (3/4 page width)

            dbc.Col([

                # 4x2 Grid of Cards
                dbc.Row([
                    dbc.Col([
                        html.H5('Commodity Indexed Prices', style={'color': colors['text']}),
                        dbc.Card([
                            dcc.Graph(id='commodity-price-series')
                            ], style={'backgroundColor': colors['background']})
                        ], width=6),
                    dbc.Col([
                        html.H5('Commodity Prices YoY', style={'color': colors['text']}),
                        dbc.Card([
                            dcc.Graph(id='commodity-price-yoy-series')
                        ], style={'backgroundColor': colors['background']})
                    ], width=6)
                ]),
                dbc.Row([
                    dbc.Col([
                        html.H5('Index Fund Indexed Prices', style={'color': colors['text']}),
                        dbc.Card([
                            dcc.Graph(id='index-fund-price-series')
                        ], style={'backgroundColor': colors['background']})
                    ], width=6),
                    dbc.Col([
                        html.H5('Index Fund Prices YoY', style={'color': colors['text']}),
                        dbc.Card([
                            dcc.Graph(id='index-fund-price-yoy-series')
                        ], style={'backgroundColor': colors['background']})
                    ], width=6)
                ]),
                dbc.Row([
                    dbc.Col([
                        html.H5('ETF Indexed Prices', style={'color': colors['text']}),
                        dbc.Card([
                            dcc.Graph(id='etf-price-series')
                        ], style={'backgroundColor': colors['background']})
                    ], width=6),
                    dbc.Col([
                        html.H5('ETF Prices YoY', style={'color': colors['text']}),
                        dbc.Card([
                            dcc.Graph(id='etf-price-yoy-series')
                        ], style={'backgroundColor': colors['background']})
                    ], width=6)
                ]),
                dbc.Row([
                    dbc.Col([
                        html.H5('FX Indexed Prices', style={'color': colors['text']}),
                        dbc.Card([
                            dcc.Graph(id='fx-price-series')
                        ], style={'backgroundColor': colors['background']})
                    ], width=6),
                    dbc.Col([
                        html.H5('FX Prices YoY', style={'color': colors['text']}),
                        dbc.Card([
                            dcc.Graph(id='fx-price-yoy-series')
                        ], style={'backgroundColor': colors['background']})
                    ], width=6)
                ]),

            ], width=10),

        ], className="g-0"),  # Zero-gap for cleaner layout

    ], style={'padding': '10px'})

    return app_layout


def register_landing_page_data_callbacks(app, data):
    @app.callback(
        [dash.dependencies.Output('commodity-price-series', 'figure'),
         dash.dependencies.Output('commodity-price-yoy-series', 'figure'),
         dash.dependencies.Output('index-fund-price-series', 'figure'),
         dash.dependencies.Output('index-fund-price-yoy-series', 'figure'),
         dash.dependencies.Output('etf-price-series', 'figure'),
         dash.dependencies.Output('etf-price-yoy-series', 'figure'),
         dash.dependencies.Output('fx-price-series', 'figure'),
         dash.dependencies.Output('fx-price-yoy-series', 'figure')
         ],
        [dash.dependencies.Input('dummy-store', 'data')]
    )
    def update_line_charts(dummy: Any):
        # If we had inputs (e.g. dropdowns etc then we would make dash.dependencies.Input and then pass it here as arg
        commodity_line_price = create_asset_line_chart('commodity', 'close_price_indexed')
        commodity_line_price_yoy = create_asset_line_chart('commodity', 'close_price_yoy')

        indexfund_line_price = create_asset_line_chart('index_fund', 'close_price_indexed')
        indexfund_line_price_yoy = create_asset_line_chart('index_fund', 'close_price_yoy')

        etf_line_price = create_asset_line_chart('etf', 'close_price_indexed')
        etf_line_price_yoy = create_asset_line_chart('etf', 'close_price_yoy')

        fx_line_price = create_asset_line_chart('fx', 'close_price_indexed')
        fx_line_price_yoy = create_asset_line_chart('fx', 'close_price_yoy')

        return commodity_line_price, commodity_line_price_yoy, indexfund_line_price, indexfund_line_price_yoy, \
            etf_line_price, etf_line_price_yoy, fx_line_price, fx_line_price_yoy

    def create_asset_line_chart(asset, series):
        plot_data = data[data['AssetClass'] == asset]
        if series.endswith('yoy'):
            plot_data = plot_data.dropna(subset=[series])

        fig = px.line(plot_data, x='date', y=series, color='ticker',
                                 title=f"Plot Of {series} For {asset} <br> Across Top Products")

        fig.update_layout(
            plot_bgcolor=colors['background'],
            paper_bgcolor=colors['background'],
            font_color=colors['text'],
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis_title="Date",
            yaxis_title="Values",
        )
        return fig


def get_landing_page_layout():
    return create_container([
        create_header("Welcome to the Financial Dashboard"),
        dbc.Col([
            dbc.Row([
                dbc.Button(
                    "Comparison Page",
                    id="comparison-page-button",
                    color="primary",
                    className="mr-2",
                    style={'backgroundColor': colors['primary']}
                ),
                dbc.Button(
                    "Quarterly Reports Page",
                    id="quarterly-report-ts-data-page-button",
                    color="primary",
                    style={'backgroundColor': colors['primary']}
                ),
                dbc.Button(
                    "Balance Sheet Reports Page",
                    id="balance-sheet-report-ts-data-page-button",
                    color="primary",
                    style={'backgroundColor': colors['primary']}
                ),
                dbc.Button(
                    "Company History Overview Page",
                    id="company-stock-overview-data-page-button",
                    color="primary",
                    style={'backgroundColor': colors['primary']}
                ),
                # dbc.Button(
                #     "Discounted Cash Flow Evaluation",
                #     id="company-discounted-cashflow-calculation-page-button",
                #     color="primary",
                #     style={'backgroundColor': colors['primary']}
                # ),
            ], className="text-center", style={'marginTop': '20px'})
        ], style={'backgroundColor': colors['background'], 'color': colors['text']})
    ])
