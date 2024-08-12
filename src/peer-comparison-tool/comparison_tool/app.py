import dash
from dash import html, dcc
import pandas as pd
from dash.dependencies import Input, Output
import dash_bootstrap_components as dbc
from typing import Dict

# from .layout import create_container
from .landing_page import get_landing_page_layout
from .comparison_page import get_comparison_page_layout, register_comparison_callbacks
from .company_quarterly_report import get_quarterly_report_page_layout, register_quarterly_report_page_callbacks
from .company_balance_sheet_report import get_balance_sheet_report_page_layout, register_balance_sheet_report_page_callbacks
from .styles import colors


def create_app(data: pd.DataFrame, qfin_data: pd.DataFrame, bs_data: pd.DataFrame,
               qfin_map: Dict[str, pd.DataFrame], bs_map: Dict[str, pd.DataFrame]):

    # Initialize the Dash app
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG],suppress_callback_exceptions=True)

    # Define the app layout with a location component for URL routing
    app.layout = html.Div([
        dcc.Location(id='url', refresh=False),
        html.Div(id='page-content', style={'backgroundColor': colors['background']})
    ])

    # Callback to update the page content based on URL
    @app.callback(Output('page-content', 'children'),
                  [Input('url', 'pathname')])
    def display_page(pathname):
        if pathname == '/comparison':
            return get_comparison_page_layout(data)
        elif pathname == '/quarterly-report-ts-data':
            return get_quarterly_report_page_layout(qfin_data, qfin_map)
        elif pathname == '/balance-sheet-report-ts-data':
            return get_balance_sheet_report_page_layout(bs_data, bs_map)
        else:
            return get_landing_page_layout()

    # Callback for navigation buttons
    @app.callback(Output('url', 'pathname'),
                  [Input('comparison-page-button', 'n_clicks'),
                   Input('quarterly-report-ts-data-page-button', 'n_clicks'),
                   Input('balance-sheet-report-ts-data-page-button', 'n_clicks')])
    def navigate(n_clicks_comparison, n_clicks_quarterly, n_clicks_balance_sheet):
        ctx = dash.callback_context

        if not ctx.triggered:
            return '/'
        else:
            button_id = ctx.triggered[0]['prop_id'].split('.')[0]

        if button_id == 'comparison-page-button':
            return '/comparison'
        elif button_id == 'quarterly-report-ts-data-page-button':
            return '/quarterly-report-ts-data'
        elif button_id == 'balance-sheet-report-ts-data-page-button':
            return '/balance-sheet-report-ts-data'
        else:
            return '/'

    register_comparison_callbacks(app, data)
    register_quarterly_report_page_callbacks(app, qfin_data, qfin_map)
    register_balance_sheet_report_page_callbacks(app, bs_data, bs_map)

    # Callback to handle the "Return to Home" button click
    @app.callback(
        dash.dependencies.Output('url', 'pathname', allow_duplicate=True),
        [dash.dependencies.Input('back-to-home', 'n_clicks')],
        prevent_initial_call=True
    )
    def go_back_to_home(n_clicks):
        return '/'

    return app

