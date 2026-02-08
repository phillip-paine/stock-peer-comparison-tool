from src.peer_comparison_tool.comparison_tool.constants import DB_PATH
from src.peer_comparison_tool.data.db import initialize_db_connection
import sqlite3
from typing import Any, Dict, List

from langchain.tools import tool
from langchain.messages import HumanMessage, SystemMessage
from langchain_huggingface import ChatHuggingFace


def load_table_catalog() -> List[Dict[str, Any]]:
    """
    Load table metadata and convert it into an LLM-friendly catalog.
    """
    conn = initialize_db_connection(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            table_name,
            description
        FROM table_metadata
        ORDER BY table_name
    """)
    rows = cur.fetchall()

    conn.close()

    return [
        {
            "table": row["table_name"],
            "description": row["description"],
        }
        for row in rows
    ]


    @tool
    def read_schema(table_name: str) -> Dict[str, Any]:
        """
        Read schema information for a given table.
        """
        conn = _get_connection()
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        conn.close()

        return {
            "table": table_name,
            "columns": [
                {
                    "name": col[1],
                    "type": col[2],
                    "nullable": not bool(col[3])
                }
                for col in columns
            ]
        }


    @tool
    def run_sql_query(sql: str) -> List[Dict[str, Any]]:
        """
        Execute a read-only SQL query and return rows as dictionaries.
        Only SELECT statements are allowed.
        """
        if not _is_safe_sql(sql):
            raise ValueError("Only simple SELECT queries are allowed.")

        conn = _get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]
