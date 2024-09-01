from dash import html
import dash_bootstrap_components as dbc
from .layout import create_container, create_header
from .styles import colors


# Function to get the layout for the Landing Page
def get_landing_page_layout():
    return create_container([
        create_header("Welcome to the Financial Dashboard"),
        dbc.Row([
            dbc.Col([
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
