from dash import html, dcc
import dash_bootstrap_components as dbc

from .layout import create_container, create_header


# Function to get the layout for the Financial Time Series Page
def get_financial_time_series_page_layout(data):
    return create_container([
        create_header("Financial Time Series Page"),
        # Add content for Financial Time Series Page here using the `data`
    ])
