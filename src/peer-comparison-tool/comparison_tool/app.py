import dash
from dash import html, dcc
import pandas as pd
from dash.dependencies import Input, Output
import dash_bootstrap_components as dbc
from typing import Dict, Any

# from .layout import create_container
from .landing_page import get_landing_page_layout_v2
from .comparison_page import get_comparison_page_layout, register_comparison_callbacks
from .company_quarterly_report_page import get_quarterly_report_page_layout, register_quarterly_report_page_callbacks
from .company_balance_sheet_report_page import get_balance_sheet_report_page_layout, register_balance_sheet_report_page_callbacks
from .individual_company_overview_page import get_individual_company_overview_page_layout, \
    register_individual_company_overview_callback
from .discounted_cashflow_model_page import get_discounted_cashflow_model_page_layout, register_discounted_cashflow_model_page_callbacks
from .styles import colors


def create_app(ticker_series_data: Dict[str, Any], data: pd.DataFrame, qfin_data: pd.DataFrame, bs_data: pd.DataFrame,
               qfin_map: Dict[str, pd.DataFrame], bs_map: Dict[str, pd.DataFrame], cashflow_map: Dict[str, pd.DataFrame]):

    # Initialize the Dash app
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG],suppress_callback_exceptions=True)

    # Define the app layout with a location component for URL routing
    app.layout = html.Div([
        dcc.Location(id='url', refresh=False),
        html.Div(id='page-content', style={'backgroundColor': colors['background']})
    ])

    latest_ev_data = data[['ticker', 'enterprise_value']].set_index(keys='ticker')

    # Create the home page data:
    sub_industries = [key.split(":")[0] for key in ticker_series_data.keys() if key.startswith("Industry Index")]
    overview_data = {}
    for sub_industry in sub_industries:
        sub_industry_map = {}
        overview_data[sub_industry] = sub_industry_map

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
        elif pathname == '/company-stock-overview-data':
            return get_individual_company_overview_page_layout(ticker_series_data)
        elif pathname == '/company-discounted-cashflow-calculation':
            return get_discounted_cashflow_model_page_layout(cashflow_map, latest_ev_data)
        else:
            return get_landing_page_layout_v2(overview_data)

    # Callback for navigation buttons
    @app.callback(Output('url', 'pathname'),
                  [Input('comparison-page-button', 'n_clicks'),
                   Input('quarterly-report-ts-data-page-button', 'n_clicks'),
                   Input('balance-sheet-report-ts-data-page-button', 'n_clicks'),
                   Input('company-stock-overview-data-page-button', 'n_clicks'),
                   Input('company-discounted-cashflow-calculation-page-button', 'n_clicks')])
    def navigate(n_clicks_comparison, n_clicks_quarterly, n_clicks_balance_sheet, n_clicks_company_overview, n_clicks_company_dcf):
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
        elif button_id == 'company-stock-overview-data-page-button':
            return '/company-stock-overview-data'
        elif button_id == 'company-discounted-cashflow-calculation-page-button':
            return '/company-discounted-cashflow-calculation'
        else:
            return '/'

    register_comparison_callbacks(app, data)
    register_quarterly_report_page_callbacks(app, qfin_data, qfin_map)
    register_balance_sheet_report_page_callbacks(app, bs_data, bs_map)
    register_individual_company_overview_callback(app, ticker_series_data)
    register_discounted_cashflow_model_page_callbacks(app, cashflow_map, latest_ev_data)

    # Callback to handle the "Return to Home" button click
    @app.callback(
        dash.dependencies.Output('url', 'pathname', allow_duplicate=True),
        [dash.dependencies.Input('back-to-home', 'n_clicks')],
        prevent_initial_call=True
    )
    def go_back_to_home(n_clicks):
        return '/'

    return app

