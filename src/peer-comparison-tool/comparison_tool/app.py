import dash
from dash import html, dcc, dash_table
import plotly.express as px
import dash_bootstrap_components as dbc
import pandas as pd


def create_app(data: pd.DataFrame):
    # Initialize the Dash app
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

    # Layout of the app
    app.layout = dbc.Container([
        dbc.Row(dbc.Col(html.H1("Stock Peer Comparison Tool"), className="mb-4")),

        dbc.Row(dbc.Col(html.H2("Key Metrics Table"))),
        dbc.Row(dbc.Col(dash_table.DataTable(
            columns=[{"name": i, "id": i} for i in data.columns],
            data=data.to_dict('records'),
            style_table={'overflowX': 'auto'},
        ))),

        dbc.Row(dbc.Col(html.H2("Latest EPS Comparison"), className="mt-4")),
        dbc.Row(dbc.Col(dcc.Graph(
            figure=,
            style={"height": "70vh"}
        ))),

        dbc.Row(dbc.Col(html.H2("P/E Ratio Comparison"), className="mt-4")),
        dbc.Row(dbc.Col(dcc.Graph(
            figure=px.bar(data, x='price_eps_ratio', y='ticker', title="P/E Ratio Comparison", orientation='h'),
            style={"height": "70vh"}
        )))
    ], fluid=True)

    @app.callback(
        [dash.dependencies.Output('eps-bar-chart', 'figure'),
        dash.dependencies.Output('price-earnings-ratio-chart', 'figure')],
        [dash.dependencies.Input('sector-dropdown', 'value')]
    )
    def update_graph(selected_sectors):
        if not selected_sectors:
            # If no sectors selected, show all data
            filtered_data = data
        else:
            # Filter data based on selected sectors
            filtered_data = data[data['sector'].isin(selected_sectors)]

        # Create bar chart figure
        fig1 = px.bar(filtered_data, x='latest_eps', y='ticker', title="Latest EPS Comparison", orientation='h')
        fig2 = px.bar(filtered_data, x='price_eps_ratio', y='ticker', title="P/E Ratio Comparison", orientation='h')

        return fig1, fig2

    return app
