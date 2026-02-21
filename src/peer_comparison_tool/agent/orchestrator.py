from typing import List, Optional

from query_state_record import QueryState
from agent_tools import select_tables, read_schema, run_sql_query, generate_sql_query, summarise, validate_sql_query
from llm_utils import get_chat_model

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_query(user_question: str) -> str:
    """
    Run a full end-to-end query workflow for a user question.

    This function replaces the old ask_question() agent loop.
    """
    llm = get_chat_model()

    # 1. Initialise state
    state = QueryState(user_question=user_question)

    # 2. Let the LLM choose relevant tables (via metadata)
    state.selected_tables = select_tables(state, llm)
    logger.info("Selected tables: %s", state.selected_tables)

    # 3. Deterministically load schemas for chosen tables
    state.schemas = read_schema(state)
    logger.info("Selected table schema: %s", state.schemas)

    # 4. Ask the LLM to generate SQL using schema + question
    max_retries = 2
    for attempt in range(max_retries):
        state.sql_query = generate_sql_query(state, llm)

        validation = validate_sql_query(state, llm)

        if validation["is_valid"]:
            logger.info(f"SQL validated successfully on attempt {attempt + 1}")
            break
        else:
            logger.warning(f"Attempt {attempt + 1} failed validation: {validation['feedback']}")
            if attempt < max_retries - 1:
                # Add feedback to state for next attempt
                state.user_question = (
                    f"{state.user_question}\n\n"
                    f"Previous SQL attempt was invalid: {validation['feedback']}\n"
                    f"Please try again with a corrected query."
                )
            else:
                raise ValueError(f"Failed to generate valid SQL after {max_retries} attempts: {validation['feedback']}")


    # 5. Execute SQL against the database
    state.sql_output = run_sql_query(state.sql_query)

    # 6. Summarise results into user-facing text
    state.answer = summarise(state, llm)
    logger.info("Summary of request: %s", state.answer)

    if not state.answer:
        raise ValueError("summarise() returned an empty answer.")

    return state.answer


if __name__ == '__main__':
    test_question = "What is GS market cap in the latest data"
    response = run_query(test_question)
    print(response)
