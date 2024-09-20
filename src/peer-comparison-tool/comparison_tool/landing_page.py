from typing import Dict, Any
from dash import html, dcc
import dash_bootstrap_components as dbc
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
def get_landing_page_layout_v2(dat: Dict[str, Dict[str, Any]]):
    app_layout = html.Div([
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
                        dbc.NavLink("Discounted Cashflow Model", href="/company-discounted-cashflow-calculation", active="exact"),
                    ],
                    vertical=True,
                    pills=True,
                ), width=3
            ),

            # Main content (3/4 page width)
            dbc.Col([

                # 2x2 Grid of Cards
                dbc.Row([
                    dbc.Col(create_card("Revenue Growth", dcc.Graph(figure={})), width=6),
                    dbc.Col(create_card("Profit Margin", dcc.Graph(figure={})), width=6),
                ]),
                dbc.Row([
                    dbc.Col(create_card("Debt to Equity", dcc.Graph(figure={})), width=6),
                    dbc.Col(create_card("PE Ratio", dcc.Graph(figure={})), width=6),
                ]),

            ], width=9),

        ], className="g-0"),  # Zero-gap for cleaner layout

    ], style={'padding': '10px'})

    return app_layout


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
                dbc.Button(
                    "Discounted Cash Flow Evaluation",
                    id="company-discounted-cashflow-calculation-page-button",
                    color="primary",
                    style={'backgroundColor': colors['primary']}
                ),
            ], className="text-center", style={'marginTop': '20px'})
        ], style={'backgroundColor': colors['background'], 'color': colors['text']})
    ])
