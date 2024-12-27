import dash
from dash import html, dash_table, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import os
import pandas as pd
import plotly.graph_objects as go
from .styles import colors
from .constants import DOWNLOAD_DIR


def get_individual_company_overview_page_layout(ticker_price_data, industry_price_data,
                                                industry_metric_yoy_data):
    # TODO subset the industry_metric_yoy_data to the sub_industry - where do we choose this?
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
                    options=[{'label': ticker, 'value': ticker} for ticker in list(ticker_price_data['ticker'].unique())],
                    value=list(ticker_price_data['ticker'].unique())[0],  # Default selection - jut pick first ticker
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
                        html.Div(id='net-income-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='operating-income-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='basic-eps-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='gross-margin-metric', style={'margin-bottom': '10px'}),
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
                html.H5('(Sub-)Industry YoY Change', style={'color': colors['text']}),
                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='industry-net-income-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='industry-operating-income-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='industry-basic-eps-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='industry-gross-margin-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='industry-net-margin-metric', style={'margin-bottom': '10px'}),
                    ]),
                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),

                dbc.Card([
                    dbc.CardBody([
                        html.Div(id='industry-stock-price-metric', style={'margin-bottom': '10px'}),
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


def register_individual_company_overview_callback(app, company_info_tab, tickers_series_data, tickers_metric_data, industries_series_data,
                                                  industries_metric_data):
    @app.callback(
        [dash.dependencies.Output('stock-price-series-chart', 'figure'),
         dash.dependencies.Output('gross-margin-metric', 'children'),
         dash.dependencies.Output('operating-income-metric', 'children'),
         dash.dependencies.Output('net-income-metric', 'children'),
         dash.dependencies.Output('basic-eps-metric', 'children'),
         dash.dependencies.Output('net-margin-metric', 'children'),
         dash.dependencies.Output('stock-price-metric', 'children'),
         dash.dependencies.Output('industry-gross-margin-metric', 'children'),
         dash.dependencies.Output('industry-operating-income-metric', 'children'),
         dash.dependencies.Output('industry-net-income-metric', 'children'),
         dash.dependencies.Output('industry-basic-eps-metric', 'children'),
         dash.dependencies.Output('industry-net-margin-metric', 'children'),
         dash.dependencies.Output('industry-stock-price-metric', 'children')],
        [dash.dependencies.Input('ticker-dropdown', 'value')]
    )
    def update_charts(selected_ticker):
        if selected_ticker is None:
            return dash.no_update

        # Filter data by selected sector:
        sub_industry = company_info_tab.loc[company_info_tab["ticker"] == selected_ticker, "sub_industry"].iloc[0]
        ticker_series_data = tickers_series_data[tickers_series_data['ticker'] == selected_ticker]
        ticker_metric_data = tickers_metric_data[tickers_metric_data['ticker'] == selected_ticker]
        industry_series_data = industries_series_data[industries_series_data['sub_industry'] == sub_industry]
        industry_metric_data = industries_metric_data[industries_metric_data['sub_industry'] == sub_industry]

        ts_filtered_data = ticker_series_data[['date', 'close_price_indexed', 'close_price_indexed_yoy']]
        ts_industry_data = industry_series_data[['date', 'industry_close_price_indexed', 'industry_close_price_indexed_yoy']]
        ts_combined_data = pd.merge(ts_filtered_data, ts_industry_data, on=['date'])
        fig_stockprice = px.line(ts_combined_data, x='date', y=['close_price_indexed', 'industry_close_price_indexed'],
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
        plot_metrics = ['Basic EPS YoY', 'Net Income YoY', 'Operating Income YoY', 'Gross Margin YoY', 'Net Margin YoY']
        ticker_plot_metric_data = ticker_metric_data[plot_metrics]
        industry_plot_metric_data = industry_metric_data[plot_metrics]

        # TODO delete later:
        # revenue_yoy = ticker_data.get("Total Revenue_yoy")
        # net_income_continuing_operations_yoy = ticker_data.get("Net Income Continuous Operations_yoy")
        # eps_yoy = ticker_data.get("Basic EPS_yoy")
        # net_margin_yoy = ticker_data.get("net_margin_yoy")
        # stock_price_yoy = ticker_data.get("stock_price_yoy")

        # STOCK METRICS:

        # Update the metric
        basic_eps_yoy = ticker_plot_metric_data['Basic EPS YoY'].iloc[-1]
        basic_eps_metric = [
            html.Span(f"Basic EPS: ", style={'font-weight': 'bold'}),
            html.Span(f"{basic_eps_yoy:.2f}%", style={'color': get_color_and_arrow(basic_eps_yoy)[0]}),
            html.Span(get_color_and_arrow(basic_eps_yoy)[1], style={'color': get_color_and_arrow(basic_eps_yoy)[0], 'font-size': '20px'}),
        ]

        net_income_yoy = ticker_plot_metric_data['Net Income YoY'].iloc[-1]
        net_income_operations_metric = [
            html.Span(f"Net Income: ", style={'font-weight': 'bold'}),
            html.Span(f"{net_income_yoy:.2f}%", style={'color': get_color_and_arrow(net_income_yoy)[0]}),
            html.Span(get_color_and_arrow(net_income_yoy)[1], style={'color': get_color_and_arrow(net_income_yoy)[0], 'font-size': '20px'}),
        ]

        operating_income_yoy = ticker_plot_metric_data['Operating Income YoY'].iloc[-1]
        operating_income_metric = [
            html.Span(f"Operating Income: ", style={'font-weight': 'bold'}),
            html.Span(f"{operating_income_yoy:.2f}%", style={'color': get_color_and_arrow(operating_income_yoy)[0]}),
            html.Span(get_color_and_arrow(operating_income_yoy)[1], style={'color': get_color_and_arrow(operating_income_yoy)[0], 'font-size': '20px'}),
        ]

        net_margin_yoy = ticker_plot_metric_data['Net Margin YoY'].iloc[-1]
        net_margin_metric = [
            html.Span(f"Gross Margin: ", style={'font-weight': 'bold'}),
            html.Span(f"{net_margin_yoy:.2f}%", style={'color': get_color_and_arrow(net_margin_yoy)[0]}),
            html.Span(get_color_and_arrow(net_margin_yoy)[1], style={'color': get_color_and_arrow(net_margin_yoy)[0], 'font-size': '20px'}),
        ]

        gross_margin_yoy = ticker_plot_metric_data['Gross Margin YoY'].iloc[-1]
        gross_margin_metric = [
            html.Span(f"Net Margin: ", style={'font-weight': 'bold'}),
            html.Span(f"{gross_margin_yoy:.2f}%", style={'color': get_color_and_arrow(gross_margin_yoy)[0]}),
            html.Span(get_color_and_arrow(gross_margin_yoy)[1], style={'color': get_color_and_arrow(gross_margin_yoy)[0], 'font-size': '20px'}),
        ]

        stock_price_yoy = ts_filtered_data['close_price_indexed_yoy'].iloc[-1]
        stock_price_metric = [
            html.Span(f"Stock Price: ", style={'font-weight': 'bold'}),
            html.Span(f"{stock_price_yoy:.2f}%", style={'color': get_color_and_arrow(stock_price_yoy)[0]}),
            html.Span(get_color_and_arrow(stock_price_yoy)[1], style={'color': get_color_and_arrow(stock_price_yoy)[0], 'font-size': '20px'}),
        ]

        #########################
        # SUB-INDUSTRY METRICS:
        industry_basic_eps_yoy = industry_plot_metric_data['Basic EPS YoY'].iloc[-1]
        industry_basic_eps_metric = [
            html.Span(f"Industry Basic EPS: ", style={'font-weight': 'bold'}),
            html.Span(f"{industry_basic_eps_yoy:.2f}%", style={'color': get_color_and_arrow(industry_basic_eps_yoy)[0]}),
            html.Span(get_color_and_arrow(industry_basic_eps_yoy)[1], style={'color': get_color_and_arrow(industry_basic_eps_yoy)[0], 'font-size': '20px'}),
        ]

        industry_net_income_yoy = industry_plot_metric_data['Net Income YoY'].iloc[-1]
        industry_net_income_operations_metric = [
            html.Span(f"Industry Net Income: ", style={'font-weight': 'bold'}),
            html.Span(f"{industry_net_income_yoy:.2f}%", style={'color': get_color_and_arrow(industry_net_income_yoy)[0]}),
            html.Span(get_color_and_arrow(industry_net_income_yoy)[1], style={'color': get_color_and_arrow(industry_net_income_yoy)[0], 'font-size': '20px'}),
        ]

        industry_operating_income_yoy = industry_plot_metric_data['Operating Income YoY'].iloc[-1]
        industry_operating_income_metric = [
            html.Span(f"Industry Operating Income: ", style={'font-weight': 'bold'}),
            html.Span(f"{industry_operating_income_yoy:.2f}%", style={'color': get_color_and_arrow(industry_operating_income_yoy)[0]}),
            html.Span(get_color_and_arrow(industry_operating_income_yoy)[1], style={'color': get_color_and_arrow(industry_operating_income_yoy)[0], 'font-size': '20px'}),
        ]

        industry_net_margin_yoy = industry_plot_metric_data['Net Margin YoY'].iloc[-1]
        industry_net_margin_metric = [
            html.Span(f"Industry Net Margin: ", style={'font-weight': 'bold'}),
            html.Span(f"{industry_net_margin_yoy:.2f}%", style={'color': get_color_and_arrow(industry_net_margin_yoy)[0]}),
            html.Span(get_color_and_arrow(industry_net_margin_yoy)[1], style={'color': get_color_and_arrow(industry_net_margin_yoy)[0], 'font-size': '20px'}),
        ]

        industry_gross_margin_yoy = industry_plot_metric_data['Gross Margin YoY'].iloc[-1]
        industry_gross_margin_metric = [
            html.Span(f"Industry Gross Margin: ", style={'font-weight': 'bold'}),
            html.Span(f"{industry_gross_margin_yoy:.2f}%", style={'color': get_color_and_arrow(industry_gross_margin_yoy)[0]}),
            html.Span(get_color_and_arrow(industry_gross_margin_yoy)[1], style={'color': get_color_and_arrow(industry_gross_margin_yoy)[0], 'font-size': '20px'}),
        ]

        industry_stock_price_yoy = ts_industry_data['industry_close_price_indexed_yoy'].iloc[-1]
        industry_stock_price_metric = [
            html.Span(f"Industry Stock Price: ", style={'font-weight': 'bold'}),
            html.Span(f"{industry_stock_price_yoy:.2f}%", style={'color': get_color_and_arrow(industry_stock_price_yoy)[0]}),
            html.Span(get_color_and_arrow(industry_stock_price_yoy)[1], style={'color': get_color_and_arrow(industry_stock_price_yoy)[0], 'font-size': '20px'}),
        ]

        return fig_stockprice, basic_eps_metric, operating_income_metric, net_income_operations_metric, \
            gross_margin_metric, net_margin_metric, stock_price_metric, \
            industry_basic_eps_metric, industry_operating_income_metric, industry_net_income_operations_metric, \
            industry_gross_margin_metric, industry_net_margin_metric, industry_stock_price_metric

