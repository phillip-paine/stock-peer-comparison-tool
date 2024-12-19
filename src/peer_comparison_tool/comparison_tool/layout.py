import dash_bootstrap_components as dbc
from dash import html

from .styles import colors, common_styles


def create_container(children):
    return dbc.Container(
        children,
        style={
            'backgroundColor': colors['background'],
            'color': colors['text'],
            'padding': '20px'
        },
        fluid=True
    )


def create_header(title):
    return dbc.Row(
        dbc.Col(
            html.H1(title, style={'color': colors['text']}),
            className="text-center"
        ),
        style={'marginBottom': '20px'}
    )
