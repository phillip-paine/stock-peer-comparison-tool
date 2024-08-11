import dash
from dash import html, dash_table, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from .layout import create_container, create_header
from .styles import colors
import pandas as pd

DISPLAY_COLS = ['name', 'sector', 'price_eps_ratio', 'market_cap_MM', 'EV_EBIDTA', 'latest_eps']


def get_comparison_page_layout(data: pd.DataFrame):
    return dbc.Container([
        dbc.Row([dbc.Col(html.H1("Stock Peer Comparison Tool", style={'color': colors['text'], 'textAlign': 'center'}), width=10, className="mb-4"),
                 dbc.Col(dbc.Button("Return to Home", id="back-to-home", color="primary", className="mb-3"), width=2)
                 ], align='center'),

        dbc.Row(
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
            ])
        ),

        # Data table:
        dbc.Row(
            dbc.Col(
                dbc.Card([
                    dbc.CardHeader("Stock Info Overview", style={'color': colors['text'], 'backgroundColor': colors['background']}),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dash_table.DataTable(
                                    id='metrics-table',
                                    columns=[{"name": i, "id": i} for i in data[DISPLAY_COLS].columns],
                                    data=data.head(5).to_dict('records'),
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
                            ], width=6),
                            dbc.Col([
                                dcc.Graph(
                                    id='scatter-info-chart'
                                )
                            ], width=6)
                        ])
                    ], style={'backgroundColor': colors['background']}),
                ], style={'backgroundColor': colors['background']}), width=12
            )
        ),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Button("Toggle EPS Chart", id="collapse-eps-button", className="mb-3", color="primary"),
                        dbc.Button("Toggle P/E Ratio Chart", id="collapse-pe-ratio-button", className="mb-3", color="secondary")
                    ])
                ], style={'backgroundColor': colors['background']})
            ], width=6),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Label("Select Companies:"),
                        dcc.Dropdown(
                            id='dropdown-company',
                            options=[{'label': sec, 'value': sec} for sec in data['name']],
                            value=[data.iloc[0].loc['name'], data.iloc[1].loc['name']],  # Default selection
                            multi=True,
                            searchable=True,
                            placeholder="Select companies...",
                            style={'marginBottom': '20px'}
                        ),
                    ])
                ], style={'backgroundColor': colors['background']})
            ], width=6)
        ]),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.Collapse(
                        dcc.Graph(id='eps-bar-chart'),
                        id="collapse-eps",
                        is_open=True
                    ),
                    dbc.Collapse(
                        dcc.Graph(id='price-earnings-ratio-chart'),
                        id="collapse-pe-ratio",
                        is_open=False
                    )
                    # Add more graphs and plots here if we want
                ], style={'backgroundColor': colors['background']}),
            ], width=6),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dcc.Graph(id='radar-chart')
                    ])
                ], style={'backgroundColor': colors['background']})
            ], width=6)
        ]),

        # dbc.Row([
        #     dbc.Col([
        #         dbc.Card([
        #             dbc.CardHeader(html.H3("Radar Chart - Metric Comparison", style={'color': colors['text']})),
        #             dbc.CardBody([
        #                 html.Label("Select Companies:"),
        #                 dcc.Dropdown(
        #                     id='dropdown-company',
        #                     options=[{'label': sec, 'value': sec} for sec in data['name']],
        #                     value=[data.iloc[0].loc['name'], data.iloc[1].loc['name']],  # Default selection
        #                     multi=True,
        #                     searchable=True,
        #                     placeholder="Select companies...",
        #                     style={'marginBottom': '20px'}
        #                 ),
        #                 dcc.Graph(id='radar-chart')
        #             ])
        #         ], style={'backgroundColor': colors['background']})
        #     ], width=12)
        # ])

        # dbc.Row(dbc.Col(html.H2("Latest EPS Comparison"), className="mt-4")),
        # dbc.Row(dbc.Col(dcc.Graph(
        #     figure=,
        #     style={"height": "70vh"}
        # ))),
        #
        # dbc.Row(dbc.Col(html.H2("P/E Ratio Comparison"), className="mt-4")),
        # dbc.Row(dbc.Col(dcc.Graph(
        #     figure=px.bar(data, x='price_eps_ratio', y='ticker', title="P/E Ratio Comparison", orientation='h'),
        #     style={"height": "70vh"}
        # )))
    ], fluid=True, style={'backgroundColor': colors['background']})


def register_comparison_callbacks(app: dash.Dash, data: pd.DataFrame):
    @app.callback(
        [dash.dependencies.Output("collapse-eps", "is_open"),
         dash.dependencies.Output("collapse-pe-ratio", "is_open")],
        [dash.dependencies.Input("collapse-eps-button", "n_clicks"),
         dash.dependencies.Input("collapse-pe-ratio-button", "n_clicks")],
        [dash.dependencies.State("collapse-eps", "is_open"),
         dash.dependencies.State("collapse-pe-ratio", "is_open")],
    )
    def toggle_charts(n_clicks_eps, n_clicks_pe, is_open_eps, is_open_pe):
        ctx = dash.callback_context

        if not ctx.triggered:
            return False, False

        button_id = ctx.triggered[0]['prop_id'].split('.')[0]

        if button_id == "collapse-eps-button":
            return not is_open_eps, False
        elif button_id == "collapse-pe-ratio-button":
            return False, not is_open_pe
        return False, False

    @app.callback(
        [dash.dependencies.Output('metrics-table', 'data'),
         dash.dependencies.Output('eps-bar-chart', 'figure'),
         dash.dependencies.Output('price-earnings-ratio-chart', 'figure')],
        dash.dependencies.Output('scatter-info-chart', 'figure'),
        [dash.dependencies.Input('sector-dropdown', 'value')]
    )
    def update_graph(selected_sectors):
        if not selected_sectors:
            # If no sectors selected, show all data
            filtered_data = data
        else:
            # Filter data based on selected sectors
            filtered_data = data[data['sector'].isin(selected_sectors)]

        # Update DataTable
        table_data = filtered_data.sort_values(by=['price_eps_ratio'], ascending=False).to_dict('records')

        # Create bar chart figure
        fig1 = px.bar(filtered_data, x='latest_eps', y='ticker', title="Latest EPS Comparison", orientation='h')
        fig2 = px.bar(filtered_data, x='price_eps_ratio', y='ticker', title="P/E Ratio Comparison", orientation='h')
        fig3 = px.scatter(filtered_data, x='latest_eps', y='price_eps_ratio', text='ticker',
                          hover_data={'market_cap_MM': True, 'price_to_book': True, 'EV_EBIDTA': True},
                          title="EPS vs. P/E Ratio Scatter Chart")

        # Update figure layout for dark theme
        fig1.update_layout(
            plot_bgcolor=colors['background'],
            paper_bgcolor=colors['background'],
            font_color=colors['text'],
            margin=dict(l=20, r=20, t=30, b=20)
        )
        fig2.update_layout(
            plot_bgcolor=colors['background'],
            paper_bgcolor=colors['background'],
            font_color=colors['text'],
            margin=dict(l=20, r=20, t=30, b=20)
        )
        fig3.update_layout(
            plot_bgcolor=colors['background'],
            paper_bgcolor=colors['background'],
            font_color=colors['text'],
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis=dict(range=[0, max(filtered_data['latest_eps']) * 1.1]),
            yaxis=dict(range=[0, max(filtered_data['price_eps_ratio']) * 1.1])
        )

        fig3.update_traces(textposition='bottom center', marker=dict(color='red', size=10, line=dict(width=2, color='DarkSlateGrey')), selector=dict(mode='markers+text'))

        return table_data, fig1, fig2, fig3

    @app.callback(
        [dash.dependencies.Output('radar-chart', 'figure')],
        [dash.dependencies.Input('dropdown-company', 'value')]  # Example dropdown for company selection
    )
    def update_radar_chart(selected_companies):
        fig = go.Figure()

        metrics = ['market_cap_MM', 'price_eps_ratio', 'price_to_book', 'return_on_equity', 'EV_EBIDTA']

        normalised_data = data[data['name'].isin(selected_companies)]

        for metric in metrics:
            # take min and max from all data? not sure about this
            min_value = data[metric].min()
            max_value = data[metric].max()
            normalised_data[metric] = (normalised_data[metric] - min_value) / (max_value - min_value)
            # dont fully normalise otherwise bunch of values at 0 which looks bad on radar chart

        for company in selected_companies:
            company_data = normalised_data[normalised_data['name'] == company][metrics].values.flatten().tolist()
            fig.add_trace(go.Scatterpolar(
                r=company_data,
                theta=metrics,
                fill='toself',
                name=company
            ))

        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 1]
                )),
            showlegend=True,
            title='Metric Comparison Radar Chart',
            plot_bgcolor=colors['background'],
            paper_bgcolor=colors['background'],
            font_color=colors['text']
        )

        # fig.update_layout(
        #     polar=dict(
        #         radialaxis=dict(visible=True)
        #     ),
        #     showlegend=True,
        #     title='Metric Comparison Radar Chart'
        # )
        #
        # # Update range for each radial axis
        # for i, metric in enumerate(metrics):
        #     fig.update_layout(polar=dict(radialaxis=dict(range=[data[metric].min(), data[metric].max()])))

        return [fig]
