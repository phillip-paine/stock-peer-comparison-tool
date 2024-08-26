import dash
from dash import html, dash_table, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import os
import pandas as pd
import plotly.graph_objects as go
from .styles import colors
from .constants import DOWNLOAD_DIR


def get_individual_company_overview_page_layout(data):
    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Recent Company Performance", style={'color': colors['text'], 'textAlign': 'center'}), width=10,
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
            ])
        ]),

        dbc.Row([
            dbc.Col([
                html.H5('Stock Price History', style={'color': colors['text']}),
                dbc.Card([
                    dcc.Graph(id='stock-price-series-chart')
                ], style={'backgroundColor': colors['background']}),
            ], width=8),

            dbc.Col([
                html.H5('Key Metrics YoY Change', style={'color': colors['text']}),
                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='revenue-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='net-income-operations-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='basic-eps-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='net-margin-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='stock-price-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),
            ], width=2),

            dbc.Col([
                html.H5('Industry YoY Change', style={'color': colors['text']}),
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.Span(f"Revenue: ", style={'font-weight': 'bold'}),
                            html.Span(f"{data['industry']['Total Revenue_yoy']:.2f}%", style={'color': get_color_and_arrow(data['industry']['Total Revenue_yoy'])[0]}),
                            html.Span(get_color_and_arrow(data['industry']['Total Revenue_yoy'])[1], style={'color': get_color_and_arrow(data['industry']['Total Revenue_yoy'])[0], 'font-size': '20px'}),
                        ]),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.Span(f"Net Income: ", style={'font-weight': 'bold'}),
                            html.Span(f"{data['industry']['Net Income Continuous Operations_yoy']:.2f}%", style={'color': get_color_and_arrow(data['industry']['Net Income Continuous Operations_yoy'])[0]}),
                            html.Span(get_color_and_arrow(data['industry']['Net Income Continuous Operations_yoy'])[1], style={'color': get_color_and_arrow(data['industry']['Net Income Continuous Operations_yoy'])[0], 'font-size': '20px'}),
                        ], style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.Span(f"EPS: ", style={'font-weight': 'bold'}),
                            html.Span(f"{data['industry']['Basic EPS_yoy']:.2f}%", style={'color': get_color_and_arrow(data['industry']['Basic EPS_yoy'])[0]}),
                            html.Span(get_color_and_arrow(data['industry']['Basic EPS_yoy'])[1], style={'color': get_color_and_arrow(data['industry']['Basic EPS_yoy'])[0], 'font-size': '20px'}),
                        ], style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.Span(f"Net Margin: ", style={'font-weight': 'bold'}),
                            html.Span(f"{data['industry']['net_margin_yoy']:.2f}%", style={'color': get_color_and_arrow(data['industry']['net_margin_yoy'])[0]}),
                            html.Span(get_color_and_arrow(data['industry']['net_margin_yoy'])[1], style={'color': get_color_and_arrow(data['industry']['net_margin_yoy'])[0], 'font-size': '20px'}),
                        ], style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.Span(f"Stock Price: ", style={'font-weight': 'bold'}),
                            html.Span(f"{data['industry']['stock_price_yoy']:.2f}%", style={'color': get_color_and_arrow(data['industry']['stock_price_yoy'])[0]}),
                            html.Span(get_color_and_arrow(data['industry']['stock_price_yoy'])[1], style={'color': get_color_and_arrow(data['industry']['stock_price_yoy'])[0], 'font-size': '20px'}),
                        ], style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),
            ], width=2),
        ]),

    ], fluid=True, style={'backgroundColor': colors['background']})


# Function to determine color and arrow
def get_color_and_arrow(change):
    if change > 0:
        return 'green', '↑'
    elif change < 0:
        return 'red', '↓'
    else:
        return 'grey', '→'


def register_individual_company_overview_callback(app, data):
    @app.callback(
        [dash.dependencies.Output('stock-price-series-chart', 'figure'),
         dash.dependencies.Output('revenue-metric', 'children'),
         dash.dependencies.Output('net-income-operations-metric', 'children'),
         dash.dependencies.Output('basic-eps-metric', 'children'),
         dash.dependencies.Output('net-margin-metric', 'children'),
         dash.dependencies.Output('stock-price-metric', 'children')],
        [dash.dependencies.Input('ticker-dropdown', 'value')]
    )
    def update_charts(selected_ticker):
        if selected_ticker is None:
            return dash.no_update

        # Filter data by selected sector
        ticker_data = data.get(selected_ticker)

        ts_filtered_data = ticker_data.get('stock_price_normalised_data')
        ts_industry_data = data.get('industry').get('stock_price_normalised_data')
        ts_filtered_data = pd.merge(ts_filtered_data, ts_industry_data, on=['Date'])
        fig_stockprice = px.line(ts_filtered_data, x='Date', y=['Close', 'Industry Close'],
                                 title=f"{selected_ticker} Normalised Stock Price v. Industry Index Past 12 Months")

        fig_stockprice.update_layout(
            plot_bgcolor=colors['background'],
            paper_bgcolor=colors['background'],
            font_color=colors['text'],
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis_title="Date",
            yaxis_title="Normalised Stock Price",
        )

        # metrics yoy data:
        # Calculate YoY changes (you can customize this calculation)
        revenue_yoy = ticker_data.get("Total Revenue_yoy")
        net_income_continuing_operations_yoy = ticker_data.get("Net Income Continuous Operations_yoy")
        eps_yoy = ticker_data.get("Basic EPS_yoy")
        net_margin_yoy = ticker_data.get("net_margin_yoy")
        stock_price_yoy = ticker_data.get("stock_price_yoy")

        # Update the metric
        revenue_metric = [
            html.Span(f"Revenue: ", style={'font-weight': 'bold'}),
            html.Span(f"{revenue_yoy:.2f}%", style={'color': get_color_and_arrow(revenue_yoy)[0]}),
            html.Span(get_color_and_arrow(revenue_yoy)[1], style={'color': get_color_and_arrow(revenue_yoy)[0], 'font-size': '20px'}),
        ]

        net_income_operations_metric = [
            html.Span(f"Net Income: ", style={'font-weight': 'bold'}),
            html.Span(f"{net_margin_yoy:.2f}%", style={'color': get_color_and_arrow(net_income_continuing_operations_yoy)[0]}),
            html.Span(get_color_and_arrow(net_income_continuing_operations_yoy)[1], style={'color': get_color_and_arrow(net_income_continuing_operations_yoy)[0], 'font-size': '20px'}),
        ]

        basic_eps_metric = [
            html.Span(f"EPS: ", style={'font-weight': 'bold'}),
            html.Span(f"{eps_yoy:.2f}%", style={'color': get_color_and_arrow(eps_yoy)[0]}),
            html.Span(get_color_and_arrow(eps_yoy)[1], style={'color': get_color_and_arrow(eps_yoy)[0], 'font-size': '20px'}),
        ]

        net_margin_metric = [
            html.Span(f"Net Margin: ", style={'font-weight': 'bold'}),
            html.Span(f"{net_margin_yoy:.2f}%", style={'color': get_color_and_arrow(net_margin_yoy)[0]}),
            html.Span(get_color_and_arrow(net_margin_yoy)[1], style={'color': get_color_and_arrow(net_margin_yoy)[0], 'font-size': '20px'}),
        ]

        stock_price_metric = [
            html.Span(f"Stock Price: ", style={'font-weight': 'bold'}),
            html.Span(f"{stock_price_yoy:.2f}%", style={'color': get_color_and_arrow(stock_price_yoy)[0]}),
            html.Span(get_color_and_arrow(stock_price_yoy)[1], style={'color': get_color_and_arrow(stock_price_yoy)[0], 'font-size': '20px'}),
        ]

        return fig_stockprice, revenue_metric, net_income_operations_metric, basic_eps_metric, net_margin_metric, stock_price_metric

