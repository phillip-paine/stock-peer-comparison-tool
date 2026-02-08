def _is_safe_sql(sql: str) -> bool:
    sql = sql.strip().lower()
    return sql.startswith("select") and ";" not in sql[:-1]
