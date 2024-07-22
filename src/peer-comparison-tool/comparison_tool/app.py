import dash
from dash import html, dcc
import pandas as pd
from dash.dependencies import Input, Output
import dash_bootstrap_components as dbc

# from .layout import create_container
from .landing_page import get_landing_page_layout
from .comparison_page import get_comparison_page_layout, register_comparison_callbacks
from .company_financials_temporal_view import get_financial_time_series_page_layout
from .styles import colors


def create_app(data: pd.DataFrame):

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
        elif pathname == '/financial-time-series':
            return get_financial_time_series_page_layout(data)
        else:
            return get_landing_page_layout()

    # Callback for navigation buttons
    @app.callback(Output('url', 'pathname'),
                  [Input('comparison-page-button', 'n_clicks'),
                   Input('financial-time-series-page-button', 'n_clicks')])
    def navigate(n_clicks_comparison, n_clicks_financial):
        ctx = dash.callback_context

        if not ctx.triggered:
            return '/'
        else:
            button_id = ctx.triggered[0]['prop_id'].split('.')[0]

        if button_id == 'comparison-page-button':
            return '/comparison'
        elif button_id == 'financial-time-series-page-button':
            return '/financial-time-series'
        else:
            return '/'

    register_comparison_callbacks(app, data)

    # Callback to handle the "Return to Home" button click
    @app.callback(
        dash.dependencies.Output('url', 'pathname', allow_duplicate=True),
        [dash.dependencies.Input('back-to-home', 'n_clicks')],
        prevent_initial_call=True
    )
    def go_back_to_home(n_clicks):
        return '/'

    return app

