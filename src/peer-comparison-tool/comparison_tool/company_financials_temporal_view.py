import dash
from dash import html, dash_table, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from .styles import colors

import pandas as pd

from .layout import create_container, create_header


# Function to get the layout for the Financial Time Series Page
def get_financial_time_series_page_layout(data):
    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Stock Financials Over Time", style={'color': colors['text'], 'textAlign': 'center'}), width=10,
                className="mb-4"),
            dbc.Col(dbc.Button("Return to Home", id="back-to-home", color="primary", className="mb-3"), width=2)
        ], align='center'
        ),

        dbc.Row([
            dbc.Col([
                html.Label("Select Sectors:", style={'color': colors['text']}),
                dcc.Dropdown(
                    id='sector-dropdown',
                    options=[{'label': sector, 'value': sector} for sector in data['sector'].unique()],
                    value=[data['sector'].iloc[0]],  # Default selection - jut pick first sector? or leave blank?
                    multi=True,
                    searchable=True,
                    placeholder="Select sectors...",
                    style={'marginBottom': '15px'}
                )
            ], width=6),
            dbc.Col([
                html.Label("Select Metric:", style={'color': colors['text']}),
                dcc.Dropdown(
                    id='metric-dropdown',
                    options=[
                        {'label': 'Gross Margin', 'value': 'Gross Margin'},
                        {'label': 'Operating Income', 'value': 'Operating Income'},
                        {'label': 'EPS', 'value': 'Basic EPS'}
                    ],
                    value='Gross Margin',
                    multi=False,
                    searchable=True,
                    placeholder="Select a metric...",
                    style={'marginBottom': '20px'}
                ),
            ], width=6),
        ]),
        dbc.Row([
            dbc.Col(dcc.Graph(id='time-series-chart', config={'displayModeBar': False}), width=12)
        ])

    ], fluid=True, style={'backgroundColor': colors['background']})


def register_time_series_callbacks(app, data):
    @app.callback(
        dash.dependencies.Output('time-series-chart', 'figure'),
        [dash.dependencies.Input('sector-dropdown', 'value'),
         dash.dependencies.Input('metric-dropdown', 'value')]
    )
    def update_time_series_chart(selected_sectors, selected_metric):
        if selected_sectors is None or selected_metric is None:
            return dash.no_update

        # Filter data by selected sector
        if not selected_sectors:
            # If no sectors selected, show all data
            filtered_data = data
        else:
            # Filter data based on selected sectors
            filtered_data = data[data['sector'].isin(selected_sectors)]

        # Create time series plot
        fig = px.line(filtered_data, x='date', y=selected_metric, color='ticker',
                      title=f"{selected_metric} over Time",
                      labels={'date': 'Quarter', selected_metric: selected_metric},
                      markers=True)

        fig.update_layout(
            plot_bgcolor=colors['background'],
            paper_bgcolor=colors['background'],
            font_color=colors['text'],
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis_title="Date",
            yaxis_title=selected_metric,
        )
        fig.update_traces(marker=dict(size=8), line=dict(width=2))

        return fig
