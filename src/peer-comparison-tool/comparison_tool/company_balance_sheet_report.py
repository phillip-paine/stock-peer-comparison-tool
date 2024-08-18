import dash
from dash import html, dash_table, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from .styles import colors
import os
from .constants import DOWNLOAD_DIR


def get_balance_sheet_report_page_layout(data, export_data_map):
    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Company Balance Sheet Report Time Series", style={'color': colors['text'], 'textAlign': 'center'}), width=10,
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
            ], width=4),
            dbc.Col([
                html.Label("Select Metric:", style={'color': colors['text']}),
                dcc.Dropdown(
                    id='metric-dropdown',
                    options=[
                        {'label': 'Quick Ratio', 'value': 'Quick Ratio'},
                        {'label': 'Equity Ratio', 'value': 'Equity Ratio'},
                        {'label': 'Debt-to-Equity Ratio', 'value': 'Debt-to-Equity Ratio'}
                    ],
                    value='Quick Ratio',
                    multi=False,
                    searchable=True,
                    placeholder="Select a metric...",
                    style={'marginBottom': '20px'}
                ),
            ], width=4),
            dbc.Col([
                html.Label(["Select Ticker to Export"], style={'color': colors['text']}),
                dcc.Dropdown(
                    id='ticker-bs-export-dropdown',
                    options=[{'label': ticker, 'value': ticker} for ticker in export_data_map.keys()],
                    searchable=True,
                    value=list(export_data_map.keys())[0],  # Set default value
                    style={'width': '80%'}
                ),
            ], width=3),
            dbc.Col([
                html.Button('Export Data', id='export-bsdata-button', n_clicks=0),
                dcc.Download(id='download-bs-csv'),
                html.Div(id='display-data')
            ], width=1),
        ]),
        dbc.Row([
            dbc.Col(dcc.Graph(id='bs-time-series-chart', config={'displayModeBar': False}), width=12)
        ])

    ], fluid=True, style={'backgroundColor': colors['background']})


def register_balance_sheet_report_page_callbacks(app, data, bs_map):
    @app.callback(
        dash.dependencies.Output('bs-time-series-chart', 'figure'),
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

        filtered_data.sort_values(by=['date'], inplace=True)

        # Create time series plot
        fig = px.line(filtered_data, x='date', y=selected_metric, color='ticker',
                      title=f"{selected_metric} over Time",
                      labels={'date': 'Year', selected_metric: selected_metric},
                      hover_data={data_col: True for data_col in data.columns if data_col not in['date']},
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

    @app.callback(
        dash.dependencies.Output('download-bs-csv', 'data'),
        dash.dependencies.Input('export-bsdata-button', 'n_clicks'),
        dash.dependencies.Input('ticker-bs-export-dropdown', 'value'),
        prevent_initial_call=True
    )
    def export_data(n_clicks, selected_ticker):
        if n_clicks > 0 and selected_ticker:
            # Get the selected balance sheet DataFrame
            df = bs_map[selected_ticker]

            # Convert the DataFrame to a CSV string
            csv_string = df.to_csv(index=False)

            # Return the data for download
            filename = f"{selected_ticker}_historical_10K_balance_sheet_{most_recent_report_date(df)}.csv"
            filepath = os.path.join(os.path.expanduser(DOWNLOAD_DIR), filename)
            if os.path.exists(filepath):
                return dash.no_update
            else:
                return dict(content=csv_string, filename=filepath, type='text/csv')


def most_recent_report_date(ticker_data):
    return ticker_data['date'].iloc[-1]
