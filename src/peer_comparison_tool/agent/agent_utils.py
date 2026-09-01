import sqlite3
from src.peer_comparison_tool.comparison_tool.constants import DB_PATH
from src.peer_comparison_tool.data_old.db import initialize_db_connection
from typing import Any, Dict, List
import re
import json


def _is_safe_sql(sql: str) -> bool:
    sql = sql.strip().lower()
    return sql.startswith("select") and ";" not in sql[:-1]


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
        FROM metadata
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


def get_schema_from_db(table_name: str) -> dict:
    # Validate table name to prevent SQL injection
    # (PRAGMA doesn't support parameterized queries)
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', table_name):
        raise ValueError(f"Invalid table name: '{table_name}'")

    try:
        conn = initialize_db_connection(DB_PATH)
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()

        # Fetch table description from metadata
        desc_cursor = conn.execute(
            "SELECT description FROM metadata WHERE table_name = ?",
            (table_name,)
        )
        desc_row = desc_cursor.fetchone()
        description = desc_row[0] if desc_row else None

    except sqlite3.Error as e:
        raise RuntimeError(f"Database error while fetching schema: {e}") from e
    finally:
        conn.close()

    if not columns:
        raise ValueError(f"Table '{table_name}' not found or has no columns.")

    return {
        "table": table_name,
        "description": description,
        "columns": [
            {
                "name": col[1],
                "type": col[2],
                "nullable": not bool(col[3]),
            }
            for col in columns
        ],
    }


def format_schema_block(schemas: dict[str, dict]) -> str:
    """
    Format schemas into a human-readable text block for LLM prompts.

    Args:
        schemas: Dict of table schemas with columns, description, and optional sample_row

    Returns:
        Formatted string with table descriptions, columns, and sample data
    """
    return "\n\n".join(
        f"TableName: {table}\n"
        f"Description: {meta.get('description', 'No description available')}\n"
        f"Columns:\n" +
        "\n".join(f"  - {col['name']} ({col['type']})" for col in meta["columns"]) +
        (f"\n\nSampleRow: {json.dumps(meta.get('sample_row', {}), default=str)}"
         if meta.get('sample_row') else "")
        for table, meta in schemas.items()
    )
