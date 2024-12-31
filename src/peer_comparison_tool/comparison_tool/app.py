import dash
from dash import html, dcc
import pandas as pd
from dash.dependencies import Input, Output
import dash_bootstrap_components as dbc
from typing import Dict, Any

# from .layout import create_container
from .landing_page import get_landing_page_layout_v2, register_landing_page_data_callbacks
from .comparison_page import get_comparison_page_layout, register_comparison_callbacks
from .company_quarterly_report_page import get_quarterly_report_page_layout, register_quarterly_report_page_callbacks
from .company_balance_sheet_report_page import get_balance_sheet_report_page_layout, register_balance_sheet_report_page_callbacks
from .individual_company_overview_page import get_individual_company_overview_page_layout, \
    register_individual_company_overview_callback
from .discounted_cashflow_model_page import get_discounted_cashflow_model_page_layout, register_discounted_cashflow_model_page_callbacks
from .styles import colors

from src.peer_comparison_tool.data.queries import get_table_data_query
from src.peer_comparison_tool.data.db_utils import fetch_table_data


def create_app(db_conn):
    # TODO remove:
    # (ticker_series_data: Dict[str, Any], data: pd.DataFrame, qfin_data: pd.DataFrame, bs_data: pd.DataFrame,
    # qfin_map: Dict[str, pd.DataFrame], bs_map: Dict[str, pd.DataFrame], cashflow_map: Dict[str, pd.DataFrame]
    # TODO get data from sql tables (should be in right format mostly)
    # Note the map parameters (cashflow_map) etc are ticker:df key-value pairs, where the df is used for the data
    # qfin_map, bs_map and cashflow_map are all these maps

    # Initialize the Dash app
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG],suppress_callback_exceptions=True)

    # Define the app layout with a location component for URL routing
    app.layout = html.Div([
        dcc.Location(id='url', refresh=False),
        html.Div(id='page-content', style={'backgroundColor': colors['background']})
    ])

    # TODO abstract this data prelims away from this function
    economic_data = fetch_table_data(db_conn, 'asset_class_time_series')

    # Retrieve data from connection:  # TODO only retrieve what we need, do this later.
    snapshot_recent_metrics = fetch_table_data(db_conn, 'ticker_most_recent_metric_data')
    company_info = fetch_table_data(db_conn, 'company_info')
    snapshot_recent_metrics = pd.merge(snapshot_recent_metrics, company_info, on='ticker', how='left')
    # TODO move this elsewhere:
    snapshot_recent_metrics['market_cap_MM'] = snapshot_recent_metrics['market_cap'].clip(lower=1) / 1_000_000
    data_cluster = fetch_table_data(sql_conn=db_conn, table_name='cluster_table', most_recent=True)
    data_cluster.rename(columns={"cluster_membership": "label"}, inplace=True)
    snapshot_recent_metrics = pd.merge(snapshot_recent_metrics, data_cluster[['ticker', 'label']], on=['ticker'])
    # snapshot_recent_metrics = pd.read_sql_query(sql=get_table_data_query, con=db_conn, params=['ticker_most_recent_metric_data'])
    # we can calculate EV here from stock_price X number of shareholds
    latest_ev_data = snapshot_recent_metrics[['ticker', 'enterprise_value']].set_index(keys='ticker')

    # Create the home page data:
    ticker_series_data = fetch_table_data(db_conn, 'ticker_time_series')
    ticker_series_data = pd.merge(ticker_series_data, company_info, on='ticker', how='left')
    ticker_metric_yoy_data = fetch_table_data(db_conn, 'ticker_metrics_yoy')
    ticker_metric_yoy_data = pd.merge(ticker_metric_yoy_data, company_info, on='ticker', how='left')
    ticker_series_yoy_data = fetch_table_data(db_conn, 'ticker_ts_yoy')
    ticker_series_data = pd.merge(ticker_series_data, ticker_series_yoy_data, on=['ticker', 'date'], how='left')
    ticker_series_data.sort_values(by=['ticker', 'date'], ascending=True, inplace=True)
    ticker_metric_yoy_data.sort_values(by=['ticker', 'date'], ascending=True, inplace=True)

    # ticker_series_data = pd.read_sql_query(sql=get_table_data_query, con=db_conn, params=['ticker_time_series'])
    # And the industry_series_data (aggregated from ticker data)

    industry_series_data = fetch_table_data(db_conn, 'industry_time_series')
    industry_series_yoy_data = fetch_table_data(db_conn, 'industry_time_series_yoy')
    industry_series_data = pd.merge(industry_series_data, industry_series_yoy_data, on=['sub_industry', 'date'], how='left')
    industry_metrics_yoy_data = fetch_table_data(db_conn, 'industry_metrics_yoy')
    industry_series_data.sort_values(by=['sub_industry', 'date'], ascending=True, inplace=True)
    # TODO we need to standardise the index column:
    industry_series_data['first_indexed_value'] = industry_series_data.groupby(['sub_industry'])['industry_close_price_indexed'].transform('first')
    industry_series_data['industry_close_price_indexed'] = industry_series_data['industry_close_price_indexed'] / industry_series_data['first_indexed_value'] * 100
    industry_metrics_yoy_data.sort_values(by=['sub_industry', 'date'], ascending=True, inplace=True)

    # don't need this anymore? TODO remove if we dont
    # sub_industries = [key.split(":")[0] for key in ticker_series_data.keys() if key.startswith("Industry Index")]
    # overview_data = {}
    # for sub_industry in sub_industries:
    #     sub_industry_map = {}
    #     overview_data[sub_industry] = sub_industry_map

    # Quarterly-financials:
    qfin_data = fetch_table_data(db_conn, 'quarterly_financial_data', force_date_conversion=True)
    qfin_data = pd.merge(qfin_data, company_info, on=['ticker'], how='left')
    # qfin_data = pd.read_sql_query(sql=get_table_data_query, con=db_conn, params=['quarterly_financial_data'])

    # Balance Sheet financials:
    bs_data = fetch_table_data(db_conn, 'balance_sheet_data', force_date_conversion=True)
    bs_data = pd.merge(bs_data, company_info, on=['ticker'], how='left')
    # bs_data = pd.read_sql_query(sql=get_table_data_query, con=db_conn, params=['balance_sheet_data'])

    # Callback to update the page content based on URL
    @app.callback(Output('page-content', 'children'),
                  [Input('url', 'pathname')])
    def display_page(pathname):
        if pathname == '/comparison':
            return get_comparison_page_layout(snapshot_recent_metrics)  # data:
        elif pathname == '/quarterly-report-ts-data':
            return get_quarterly_report_page_layout(qfin_data)
        elif pathname == '/balance-sheet-report-ts-data':
            return get_balance_sheet_report_page_layout(bs_data)
        elif pathname == '/company-stock-overview-data':
            return get_individual_company_overview_page_layout(ticker_series_data,
                                                               industry_series_data, industry_metrics_yoy_data)
        # TODO add cashflow df back in
        # elif pathname == '/company-discounted-cashflow-calculation':
        #     return get_discounted_cashflow_model_page_layout(cashflow_map, latest_ev_data)
        else:
            return get_landing_page_layout_v2(economic_data=economic_data)  # TODO add high-level data here?

    # Callback for navigation buttons
    @app.callback(Output('url', 'pathname'),
                  [Input('comparison-page-button', 'n_clicks'),
                   Input('quarterly-report-ts-data-page-button', 'n_clicks'),
                   Input('balance-sheet-report-ts-data-page-button', 'n_clicks'),
                   Input('company-stock-overview-data-page-button', 'n_clicks'),
                   Input('company-discounted-cashflow-calculation-page-button', 'n_clicks')])
    def navigate(n_clicks_comparison, n_clicks_quarterly, n_clicks_balance_sheet, n_clicks_company_overview, n_clicks_company_dcf):
        ctx = dash.callback_context

        if not ctx.triggered:
            return '/'
        else:
            button_id = ctx.triggered[0]['prop_id'].split('.')[0]

        if button_id == 'comparison-page-button':
            return '/comparison'
        elif button_id == 'quarterly-report-ts-data-page-button':
            return '/quarterly-report-ts-data'
        elif button_id == 'balance-sheet-report-ts-data-page-button':
            return '/balance-sheet-report-ts-data'
        elif button_id == 'company-stock-overview-data-page-button':
            return '/company-stock-overview-data'
        # elif button_id == 'company-discounted-cashflow-calculation-page-button':
        #     return '/company-discounted-cashflow-calculation'
        else:
            return '/'

    register_landing_page_data_callbacks(app, economic_data)
    register_comparison_callbacks(app, snapshot_recent_metrics)
    register_quarterly_report_page_callbacks(app, qfin_data)
    register_balance_sheet_report_page_callbacks(app, bs_data)
    register_individual_company_overview_callback(app, company_info, ticker_series_data, ticker_metric_yoy_data,
                                                  industry_series_data, industry_metrics_yoy_data)
    # register_discounted_cashflow_model_page_callbacks(app, cashflow_map, latest_ev_data)

    # Callback to handle the "Return to Home" button click
    @app.callback(
        dash.dependencies.Output('url', 'pathname', allow_duplicate=True),
        [dash.dependencies.Input('back-to-home', 'n_clicks')],
        prevent_initial_call=True
    )
    def go_back_to_home(n_clicks):
        return '/'

    return app

