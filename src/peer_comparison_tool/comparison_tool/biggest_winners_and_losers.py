import dash
from dash import html, dash_table, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import os
import plotly.graph_objects as go
from .styles import colors
import pandas as pd

DISPLAY_COLS = ['name', 'ticker', 'industry', 'sub_industry', 'close_price_indexed_dod']  # 'price_change', 'signifiance']
# significance is some measure of price change and historical vol.


def get_biggest_winners_and_losers_page_layout(data: pd.DataFrame):

    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Analysing Recent Winners and Losers", style={'color': colors['text'], 'textAlign': 'center'}), width=10,
                className="mb-4"),
            dbc.Col(dbc.Button("Return to Home", id="back-to-home", color="primary", className="mb-3"), width=2)
        ], align='center'
        ),

        dbc.Row([
            dbc.Col([
                html.Label("Select GICS Sector:", style={'color': colors['text']}),
                dcc.Dropdown(
                    id='sector-dropdown2',
                    options=[{'label': sector, 'value': sector} for sector in data['sector'].unique()],
                    value=[data['sector'].iloc[0]],  # Default selection - jut pick first sector? or leave blank?
                    multi=True,
                    searchable=True,
                    style={'marginBottom': '15px'}
                )
            ], width=3),
            dbc.Col([
                html.Label("Select GICS Sub-industry:", style={'color': colors['text']}),
                dcc.Dropdown(
                    id='sub-sector-dropdown2',
                    # options=[{'label': sector, 'value': sector} for sector in data['sub_industry'].unique()],
                    # value=[data['sub_industry'].iloc[0]],  # Default selection - jut pick first sector? or leave blank?
                    multi=True,
                    searchable=True,
                    placeholder="Select a sub-industry",
                    style={'marginBottom': '15px'}
                )
            ], width=3),
        ]),

        dbc.Row(
            # Data table:
            dbc.Col(
                dbc.Card([
                    dbc.CardHeader("Stock Info Overview", style={'color': colors['text'], 'backgroundColor': colors['background']}),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dash_table.DataTable(
                                    id='big-movers-table',
                                    columns=[{"name": i, "id": i} for i in DISPLAY_COLS],
                                    data=data.head(5).to_dict('records'),
                                    sort_action='native',
                                    sort_mode='multi',
                                    fixed_rows={'headers': True},
                                    style_table={
                                        # 'height': '300px',  # Fixed height of table
                                        'overflowY': 'auto'  # Enable vertical scrolling
                                    },
                                    style_header={
                                        'backgroundColor': colors['background'],
                                        'color': colors['text'],
                                        'fontWeight': 'bold'
                                    },
                                    style_data={
                                        'backgroundColor': colors['background'],
                                        'color': colors['text']
                                    },
                                    style_cell={
                                        'minWidth': '150px', 'width': '150px', 'maxWidth': '150px',  # Fixed width for all cells
                                        'overflow': 'hidden',
                                        'textOverflow': 'ellipsis',
                                    }
                                )
                            ], width=9),
                            dbc.Col([
                                html.H5('(Sub-)Sector Change', style={'color': colors['text']}),
                                dbc.Card([
                                    dbc.CardBody([
                                        html.Div(id='sub-sector-day-change', style={'margin-bottom': '10px'}),
                                    ]),
                                ], style={'background-color': colors['background'], 'margin-bottom': '10px'}),
                            ], width=3)
                        ])
                    ], style={'backgroundColor': colors['background']}),
                ], style={'backgroundColor': colors['background']}), width=12
            )
        ),

    ], fluid=True, style={'backgroundColor': colors['background']})


def register_winners_and_losers_callback(app: dash.Dash, data: pd.DataFrame):
    @app.callback(
        [dash.dependencies.Output('sub-sector-dropdown2', 'options'),
         dash.dependencies.Output('big-movers-table', 'data'),
         dash.dependencies.Output('sub-sector-day-change', 'children')],
        [dash.dependencies.Input('sector-dropdown2', 'value'),
         dash.dependencies.Input('sub-sector-dropdown2', 'value'),
        ]
    )
    def update_table(selected_sector, selected_sub_sectors):
        # Update subsector dropdown options
        if not selected_sector:
            sub_sector_options = []
        else:
            # Filter subsectors based on the selected sector
            sub_sector_options = data[data['sector'].isin(selected_sector)]['sub_industry'].unique()
            sub_sector_options = [{'label': sub, 'value': sub} for sub in sub_sector_options]

        # Filter Data for sector and sub_sector
        if not selected_sector:
            # If no sectors selected, show all data
            filtered_data = data
            # Lets drop rows with any NA for now: # TODO fix me later
            filtered_data.dropna(how='any', inplace=True)
        else:
            if not selected_sub_sectors:
                # Filter data based on selected sectors
                filtered_data = data[data['sector'].isin(selected_sector)]
                filtered_data.dropna(how='any', inplace=True)
            else:
                # Filter data based on selected sub sectors
                filtered_data = data[data['sub_industry'].isin(selected_sub_sectors)]
                filtered_data.dropna(how='any', inplace=True)

        # Update DataTable
        filtered_data['close_price_indexed_dod'] = filtered_data['close_price_indexed'].pct_change(periods=1) * 100
        filtered_data['close_price_indexed_dod'] = filtered_data['close_price_indexed_dod'].round(2)
        filtered_data_recent = filtered_data.loc[filtered_data.groupby(['ticker'])['date'].idxmax()].reset_index()
        filtered_data_recent = filtered_data_recent.sort_values(by=['close_price_indexed_dod'], ascending=False)
        filtered_daily_change_average = filtered_data_recent['close_price_indexed_dod'].mean().round(2)

        table_data = pd.concat([filtered_data_recent.head(5), filtered_data_recent.tail(5)]).to_dict('records')
        return sub_sector_options, table_data, filtered_daily_change_average
