import sqlite3

import yaml
from src.peer_comparison_tool.comparison_tool.constants import DB_PATH
from src.peer_comparison_tool.data.db import initialize_db_connection


def sync_metadata_from_yaml(path: str ="table_metadata.yaml") -> None:
    with open(path) as f:
        metadata = yaml.safe_load(f)
    try:
        conn = initialize_db_connection(DB_PATH)
        cur = conn.cursor()
        for table_name, fields in metadata.items():
            cur.execute(
                """
                INSERT INTO metadata (table_name, description)
                VALUES (?, ?)
                ON CONFLICT(table_name) DO UPDATE SET
                  description = excluded.description
                """,
                (
                    table_name,
                    fields["description"]
                )
            )
        conn.commit()
    except sqlite3.Error as E:
        raise RuntimeError(f"Failed to sync metadata: {E}") from E
    finally:
        conn.close()
    return


if __name__ == '__main__':
    sync_metadata_from_yaml()
