import dash
from dash import html, dcc, dash_table
import plotly.express as px
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
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
            data=data.sample(5).to_dict('records'),
            style_table={'overflowX': 'auto'},
        ))),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H3("Charts")),
                    dbc.CardBody([
                        html.P("Select sectors to filter data:"),
                        dcc.Dropdown(
                            id='sector-dropdown',
                            options=[{'label': sector, 'value': sector} for sector in data['sector'].unique()],
                            multi=True,
                            placeholder="Select sectors...",
                            style={'width': '100%', 'marginBottom': '10px'}
                        ),
                        dcc.Graph(id='eps-bar-chart', style={'height': '300px'}),
                        dcc.Graph(id='price-earnings-ratio-chart', style={'height': '300px'}),
                        # Add more dcc.Graph components for additional charts
                    ])
                ])
            ], width=12)
        ]),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H3("Radar Chart - Metric Comparison")),
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
                        dcc.Graph(id='radar-chart')
                    ])
                ])
            ], width=12)
        ])

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

    @app.callback(
        dash.dependencies.Output('radar-chart', 'figure'),
        [dash.dependencies.Input('dropdown-company', 'value')]  # Example dropdown for company selection
    )
    def update_radar_chart(selected_companies):
        fig = go.Figure()

        metrics = ['market_cap', 'price_eps_ratio', 'price_to_book', 'return_on_equity', 'EV_EBIDTA']

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
            title='Metric Comparison Radar Chart'
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

        return fig

    return app
