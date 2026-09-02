"""
Dash app factory and routing.

Replaces the version of `create_app()` that called `fetch_table_data()` /
`get_table_data_query()` from `data_old` (retired as part of the data-layer
cutover -- that import no longer resolves at all). All data loading now goes
through `data_loader.load_dashboard_data()`, which reads via the new
`Repository` inside a `session_scope()`. Every page/layout/callback module
this file wires together is unchanged: they still just receive plain
DataFrames as arguments, so this refactor's blast radius is contained to
this file, `data_loader.py`, and `constants.py`.

Two other real bugs found while tracing this file (both fixed below, see
inline comments at the fix site):

- `register_agent_chat_callback` and `get_chat_page_layout` were referenced
  but never imported -- `from .agent_chat import ...` was missing entirely,
  so any code path that actually rendered `/compass-chat` or reached
  `register_agent_chat_callback(app)` would raise `NameError`. `agent_chat.py`
  itself imports a `your_agent_module` that doesn't exist anywhere in the
  codebase, so the feature isn't usable yet regardless -- left disabled
  (same pattern as the already-disabled discounted-cashflow page) rather
  than wired up against a module that doesn't exist. Worth asking Phillip
  whether this is planned follow-up work.
- The navigation callback compared `button_id` (a component id like
  `'biggest-winners-and-losers-page-button'`) against `"/winners-and-losers"`
  and `"/agent-chat-page-button"` -- URL paths, not component ids -- so
  neither branch could ever match, and the winners-and-losers branch
  returned a page *layout* object instead of a URL string, which would have
  raised inside Dash the moment it did match. Fixed to compare against the
  actual button ids and return the URL paths.
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html
from dash.dependencies import Input, Output

from src.peer_comparison_tool.data.database import session_scope
from src.peer_comparison_tool.data.repository import Repository

from .biggest_winners_and_losers import (
    get_biggest_winners_and_losers_page_layout,
    register_winners_and_losers_callback,
)
from .comparison_page import get_comparison_page_layout, register_comparison_callbacks
from .company_balance_sheet_report_page import (
    get_balance_sheet_report_page_layout,
    register_balance_sheet_report_page_callbacks,
)
from .company_quarterly_report_page import (
    get_quarterly_report_page_layout,
    register_quarterly_report_page_callbacks,
)
from .data_loader import load_dashboard_data
from .individual_company_overview_page import (
    get_individual_company_overview_page_layout,
    register_individual_company_overview_callback,
)
from .landing_page import get_landing_page_layout_v2, register_landing_page_data_callbacks
from .styles import colors

# discounted_cashflow_model_page and agent_chat are intentionally not wired
# up yet -- see module docstring above and the (pre-existing, commented-out)
# DCF route below.


def create_app() -> dash.Dash:
    """Build and return the Dash app, with every page's data loaded once
    up front from the database (via `settings.database_url` -- the same
    connection the data pipeline writes to)."""
    with session_scope() as session:
        data = load_dashboard_data(Repository(session))

    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG], suppress_callback_exceptions=True)

    app.layout = html.Div([
        dcc.Location(id="url", refresh=False),
        html.Div(id="page-content", style={"backgroundColor": colors["background"]}),
    ])

    @app.callback(Output("page-content", "children"), [Input("url", "pathname")])
    def display_page(pathname):
        if pathname == "/comparison":
            return get_comparison_page_layout(data.snapshot_recent_metrics)
        elif pathname == "/quarterly-report-ts-data":
            return get_quarterly_report_page_layout(data.qfin_data)
        elif pathname == "/balance-sheet-report-ts-data":
            return get_balance_sheet_report_page_layout(data.bs_data)
        elif pathname == "/company-stock-overview-data":
            return get_individual_company_overview_page_layout(
                data.ticker_series_data, data.industry_series_data, data.industry_metrics_yoy_data
            )
        elif pathname == "/winners-and-losers":
            return get_biggest_winners_and_losers_page_layout(data.ticker_series_data)
        # TODO(compass-chat): re-enable once agent_chat.py's `your_agent_module`
        # dependency exists and get_chat_page_layout/register_agent_chat_callback
        # are actually importable.
        # elif pathname == "/compass-chat":
        #     return get_chat_page_layout()
        # TODO(dcf): re-enable once cashflow_map is wired through data_loader.
        # latest_enterprise_value is already available on `data` for when
        # this comes back.
        # elif pathname == '/company-discounted-cashflow-calculation':
        #     return get_discounted_cashflow_model_page_layout(cashflow_map, data.latest_enterprise_value)
        else:
            return get_landing_page_layout_v2(economic_data=data.economic_data)

    @app.callback(
        Output("url", "pathname"),
        [
            Input("comparison-page-button", "n_clicks"),
            Input("quarterly-report-ts-data-page-button", "n_clicks"),
            Input("balance-sheet-report-ts-data-page-button", "n_clicks"),
            Input("company-stock-overview-data-page-button", "n_clicks"),
            Input("company-discounted-cashflow-calculation-page-button", "n_clicks"),
            Input("biggest-winners-and-losers-page-button", "n_clicks"),
            Input("agent-chat-page-button", "n_clicks"),
        ],
    )
    def navigate(
        n_clicks_comparison, n_clicks_quarterly, n_clicks_balance_sheet, n_clicks_company_overview,
        n_clicks_company_dcf, n_clicks_winners_and_losers, n_clicks_agent_chat,
    ):
        ctx = dash.callback_context
        if not ctx.triggered:
            return "/"
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if button_id == "comparison-page-button":
            return "/comparison"
        elif button_id == "quarterly-report-ts-data-page-button":
            return "/quarterly-report-ts-data"
        elif button_id == "balance-sheet-report-ts-data-page-button":
            return "/balance-sheet-report-ts-data"
        elif button_id == "company-stock-overview-data-page-button":
            return "/company-stock-overview-data"
        elif button_id == "biggest-winners-and-losers-page-button":
            return "/winners-and-losers"
        # elif button_id == "agent-chat-page-button":
        #     return "/compass-chat"
        # elif button_id == 'company-discounted-cashflow-calculation-page-button':
        #     return '/company-discounted-cashflow-calculation'
        else:
            return "/"

    register_landing_page_data_callbacks(app, data.economic_data)
    register_comparison_callbacks(app, data.snapshot_recent_metrics)
    register_quarterly_report_page_callbacks(app, data.qfin_data)
    register_balance_sheet_report_page_callbacks(app, data.bs_data)
    register_individual_company_overview_callback(
        app, data.company_info, data.ticker_series_data, data.ticker_metric_yoy_data,
        data.industry_series_data, data.industry_metrics_yoy_data,
    )
    register_winners_and_losers_callback(app, data.ticker_series_data)
    # register_agent_chat_callback(app)  # see module docstring
    # register_discounted_cashflow_model_page_callbacks(app, cashflow_map, data.latest_enterprise_value)

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        [Input("back-to-home", "n_clicks")],
        prevent_initial_call=True,
    )
    def go_back_to_home(n_clicks):
        return "/"

    return app


if __name__ == "__main__":
    from src.peer_comparison_tool.data.database import init_db

    init_db()
    create_app().run(debug=True)
