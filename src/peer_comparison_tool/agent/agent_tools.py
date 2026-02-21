from src.peer_comparison_tool.comparison_tool.constants import DB_PATH
from src.peer_comparison_tool.data.db import initialize_db_connection
import sqlite3
import json
from typing import Any, Dict, List
from agent_utils import _is_safe_sql, load_table_catalog, get_schema_from_db, format_schema_block
from llm_utils import call_llm
from query_state_record import QueryState
from prompt_library import SUMMARISER_PROMPT, SELECT_TABLE_PROMPT, GENERATE_SQL_PROMPT, VALIDATE_SQL_PROMPT

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
import json


def select_tables(state: QueryState, llm: BaseChatModel) -> QueryState:
    """
    Use the LLM to select the most relevant tables
    based on the user question and table metadata.
    """

    catalog = load_table_catalog()

    human_prompt = f"""
    USER QUESTION:
    {state.user_question}

    TABLE CATALOG:
    {json.dumps(catalog, indent=2)}

    Return only a JSON array of table names.
    """

    messages = [
        SystemMessage(content=SELECT_TABLE_PROMPT),
        HumanMessage(content=human_prompt),
    ]

    response = call_llm(llm, messages)

    # Expect something like: ["daily_prices"]
    selected = json.loads(response.content)

    return selected


def read_schema(state: QueryState) -> Dict[str, Any]:
    """
    Read schema information for a given table.
    """

    schemas = {}

    for table in state.selected_tables:
        schema = get_schema_from_db(table)

        # Fetch first row as sample to assist LLM
        try:
            conn = initialize_db_connection(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(f"SELECT * FROM {table} LIMIT 1")
            sample_row = cursor.fetchone()
            conn.close()

            schema["sample_row"] = dict(sample_row) if sample_row else {}
        except sqlite3.Error:
            schema["sample_row"] = {}

        schemas[table] = schema

    return schemas


def generate_sql_query(
        state: QueryState,
        llm: BaseChatModel,
) -> str:

    if not state.user_question or not state.user_question.strip():
        raise ValueError("user_question must not be empty.")
    if not state.selected_tables:
        raise ValueError("selected_tables must not be empty.")
    if not state.schemas:
        raise ValueError("schemas must not be empty.")

    schema_block = format_schema_block(state.schemas)

    human_prompt = f"""USER QUESTION:
    {state.user_question}
    
    AVAILABLE TABLES:
    {', '.join(state.selected_tables)}
    
    SCHEMAS:
    {schema_block}
    
    Write the SQL query now."""

    messages = [
        SystemMessage(content=GENERATE_SQL_PROMPT),
        HumanMessage(content=human_prompt),
    ]

    try:
        response = call_llm(llm, messages)
    except Exception as e:
        raise RuntimeError(f"LLM call failed during SQL generation: {e}") from e

    sql = response.content.strip()

    # Strip markdown code fences if the LLM ignored instructions
    if sql.startswith("```"):
        sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s*```$", "", sql)
        sql = sql.strip()

    # Ensure the query is read-only
    first_word = sql.split()[0].upper() if sql.split() else ""
    if first_word != "SELECT":
        raise ValueError(
            f"LLM returned a non-SELECT query (got '{first_word}'). Aborting for safety."
        )

    return sql


def validate_sql_query(state: QueryState, llm: BaseChatModel) -> dict:
    """
    Validate that the generated SQL query is correct and can answer the user question.

    Returns:
        dict with 'is_valid': bool and 'feedback': str (if invalid)
    """

    schema_block = format_schema_block(state.schemas)

    human_prompt = f"""The User Question:
{state.user_question}

And the Available Tables and Schema:
{schema_block}

Finally, the Query:
{state.sql_query}

Considering the available table and its schema, is this a valid SQL query?"""

    messages = [
        SystemMessage(content=VALIDATE_SQL_PROMPT),
        HumanMessage(content=human_prompt),
    ]

    try:
        response = call_llm(llm, messages)
    except Exception as e:
        raise RuntimeError(f"LLM call failed during validation: {e}") from e

    result = response.content.strip()

    if result.startswith("VALID"):
        return {"is_valid": True, "feedback": ""}
    else:
        feedback = result.replace("INVALID:", "").strip()
        return {"is_valid": False, "feedback": feedback}


def run_sql_query(sql_query: str) -> QueryState:

    if not sql_query or not sql_query.strip():
        raise ValueError("SQL query must not be empty.")

    if not _is_safe_sql(sql_query):
        raise ValueError("Only simple SELECT queries are allowed.")

    try:
        conn = initialize_db_connection(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql_query)
        rows = cursor.fetchall()
    except sqlite3.Error as e:
        raise RuntimeError(f"Database error while executing query: {e}") from e
    finally:
        conn.close()

    return [dict(row) for row in rows]


def summarise(state: QueryState, llm: BaseChatModel) -> str:

    if not state.sql_output:
        return "The query returned no results. Try rephrasing your question or checking the available data."

    if not state.sql_query:
        raise ValueError("sql_query must be set before summarising.")

    # Truncate large result sets before sending to the LLM
    max_rows = 10
    rows = state.sql_output[:max_rows]
    truncated = len(state.sql_output) > max_rows
    results_block = json.dumps(rows, indent=2, default=str)

    truncation_notice = (
        f"\n\nNote: results were truncated to {max_rows} of {len(state.sql_output)} total rows."
        if truncated else ""
    )

    human_prompt = f"""USER QUESTION:
    {state.user_question}
    
    SQL QUERY USED:
    {state.sql_query}
    
    QUERY RESULTS:
    {results_block}{truncation_notice}
    
    Summarise the results in plain English."""

    messages = [
        SystemMessage(content=SUMMARISER_PROMPT),
        HumanMessage(content=human_prompt),
    ]

    try:
        response = call_llm(llm, messages)
    except Exception as e:
        raise RuntimeError(f"LLM call failed during summarisation: {e}") from e

    answer = response.content.strip()

    if not answer:
        raise ValueError("LLM returned an empty summary.")

    return answer
