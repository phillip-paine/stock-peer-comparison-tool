from dataclasses import dataclass, field
from typing import Any

@dataclass
class QueryState:
    user_question: str
    selected_tables: list[str] = field(default_factory=list)
    schemas: dict[str, dict] = field(default_factory=dict)
    sql_query: str | None = None
    sql_output: list[dict[str, Any]] = field(default_factory=list)
    answer: str | None = None
