import dash
from dash import html, dash_table, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import os
import plotly.graph_objects as go
from .styles import colors
import pandas as pd
from your_agent_module import run_query


def get_chat_page_layout():
    return dbc.Container([
        dbc.Row([
            dbc.Col(
                html.H1("Compass Chat", style={'color': colors['text'], 'textAlign': 'center'}),
                width=10,
                className="mb-4"
            ),
            dbc.Col(
                dbc.Button("Return to Home", id="back-to-home-chat", color="primary", className="mb-3"),
                width=2
            )
        ], align='center'),

        # Question input card
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Ask a Question", style={'color': colors['text'], 'backgroundColor': colors['background']}),
                    dbc.CardBody([
                        dbc.Textarea(
                            id="chat-input",
                            placeholder="e.g., What was GS market cap most recent quarterly statement?",
                            style={'width': '100%', 'height': '100px'},
                            className="mb-3"
                        ),
                        dbc.Button("Submit", id="chat-submit", color="success", className="me-2"),
                        dbc.Button("Clear", id="chat-clear", color="secondary"),
                    ])
                ], className="mb-4")
            ], width=12)
        ]),

        # Loading spinner
        dbc.Row([
            dbc.Col(
                dcc.Loading(
                    id="loading-chat",
                    type="default",
                    children=html.Div(id="loading-output-chat")
                ),
                width=12
            )
        ]),

        # Answer display card
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Answer", style={'color': colors['text'], 'backgroundColor': colors['background']}),
                    dbc.CardBody([
                        html.Div(id="chat-answer", style={'whiteSpace': 'pre-wrap'}),
                    ])
                ], id="answer-card", style={'display': 'none'})  # Hidden initially
            ], width=12)
        ]),

        # SQL query display (optional, for debugging)
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Generated SQL", style={'color': colors['text'], 'backgroundColor': colors['background']}),
                    dbc.CardBody([
                        html.Pre(id="chat-sql", style={'backgroundColor': '#f5f5f5', 'padding': '10px'}),
                    ])
                ], id="sql-card", style={'display': 'none'})  # Hidden initially
            ], width=12, className="mt-3")
        ]),

    ], fluid=True, style={"backgroundColor": colors['background']})


def register_agent_chat_callback(app: dash.Dash):
    @app.callback(
        [dash.dependencies.Output("chat-answer", "children"),
         dash.dependencies.Output("chat-sql", "children"),
         dash.dependencies.Output("answer-card", "style"),
         dash.dependencies.Output("sql-card", "style"),
         dash.dependencies.Output("chat-input", "value")],
        [dash.dependencies.Input("chat-submit", "n_clicks"),
         dash.dependencies.Input("chat-clear", "n_clicks")],
        [dash.dependencies.State("chat-input", "value")],
        prevent_initial_call=True
    )
    def handle_chat(submit_clicks, clear_clicks, question):
        ctx = dash.callback_context

        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        button_id = ctx.triggered[0]['prop_id'].split('.')[0]

        # Clear button
        if button_id == "chat-clear":
            return "", "", {'display': 'none'}, {'display': 'none'}, ""

        # Submit button
        if not question or not question.strip():
            return "Please enter a question.", "", {'display': 'block'}, {'display': 'none'}, question

        try:
            answer, sql_query = run_query(question)

            # You can also capture the SQL from state if you modify run_query to return it
            # For now, just return the answer
            return answer, "SQL query logged in console", {'display': 'block'}, {'display': 'none'}, ""

        except Exception as e:
            return f"Error: {str(e)}", "", {'display': 'block'}, {'display': 'none'}, question
