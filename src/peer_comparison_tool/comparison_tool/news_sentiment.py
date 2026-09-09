"""
News-based sentiment / investment-grade analysis, on demand.

Replaces `analyse_recent_news()` in the old
`comparison_tool/bad_news_trading_model.py`. Two real problems fixed:

- That function's only caller (`find_bad_news_price_drops`) computed the
  investment grade for every candidate and then discarded it -- only the
  plain price-drop ticker list was ever returned. Here the grade is the
  point: `screen_news_sentiment()` returns it alongside each candidate's
  price-drop reason, sorted worst-first, so it can actually inform which
  "bad news" candidates look like a real problem versus an overreaction.
- The original asked the model for free text and parsed it with
  `.split("Investment grade:")[1].split("High-level")[0]` plus a regex
  strip -- any reply that drifts even slightly from that exact phrasing
  breaks the whole batch, with no error handling around it. This asks for
  a single JSON object instead, falls back to pulling the first `{...}`
  block out of the reply if the model wraps it in prose, and wraps each
  ticker's analysis in its own try/except so one bad response doesn't take
  down the batch.

Reuses the same LLM provider/library the `agent/` package already
standardized on -- `ChatHuggingFace` + `HuggingFaceEndpoint` via
langchain, per Phillip's call -- but does NOT import
`agent.llm_utils.get_chat_model()` directly: that module imports
`from peer_comparison_tool.comparison_tool.constants import ...` (missing
the `src.` prefix every other module in this codebase uses to import
`peer_comparison_tool`), so it doesn't actually resolve given how
everything else here is imported and run. `agent/`'s import issues are a
separate, already-tracked item (see refactor handoff notes, "`agent/`
package... still has broken `data_old` imports and relative import
issues -- needs wiring") -- fixing that package is out of scope for this
change. `get_chat_model()` below builds the identical client, just against
the working `comparison_tool.constants` values.

Nothing here is persisted: headlines and LLM grades are fetched live and
held only in the in-memory `NewsSentimentCache` for the running dashboard
process (per Phillip's call -- same-day caching, not a DB table), cleared
whenever the calendar date rolls over.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from src.peer_comparison_tool.comparison_tool.constants import HUGGINGFACE_API_TOKEN, HUGGINGFACE_MODEL
from src.peer_comparison_tool.data.transforms.news_headlines import extract_headline_title

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an AI investment analyst. You will be given a list of recent news "
    "headlines for one company. Considering the whole list together, judge whether "
    "the news is good or bad for the company's short-to-medium-term outlook.\n\n"
    "Respond with ONLY a single JSON object, no other text, in exactly this shape:\n"
    '{"summary": "<one or two sentence summary of what the news means for the company>", '
    '"investment_grade": <integer 1-10, where 1 = very positive for the company, '
    "5 = neutral/average, 10 = very negative>}"
)


class ChatModel(Protocol):
    """Minimal interface this module needs from an LLM client -- satisfied by
    langchain's `ChatHuggingFace` (`.invoke(messages) -> AIMessage` with a
    `.content` attribute) and by `FakeChatModel` in the test suite."""

    def invoke(self, messages: list[Any]) -> Any:
        ...


def get_chat_model() -> ChatModel:
    """Build a `ChatHuggingFace(HuggingFaceEndpoint(...))` client -- the
    same construction `agent.llm_utils.get_chat_model()` uses (see module
    docstring for why that function isn't imported directly here).

    Raises `RuntimeError` if `HUGGINGFACE_API_TOKEN` isn't set, rather than
    failing at import time -- callers (the dashboard page) should invoke
    this lazily, on first use, so the rest of the app keeps working
    without a token configured.
    """
    from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

    if not HUGGINGFACE_API_TOKEN:
        raise RuntimeError(
            "HUGGINGFACE_API_TOKEN is not set -- news sentiment analysis needs it. "
            "Set the environment variable to enable this feature."
        )
    return ChatHuggingFace(
        llm=HuggingFaceEndpoint(huggingfacehub_api_token=HUGGINGFACE_API_TOKEN, repo_id=HUGGINGFACE_MODEL)
    )


def _extract_headline(news_item: dict[str, Any]) -> str | None:
    """Re-exported from `data/transforms/news_headlines.py` (moved there so
    `market_conditions.py`'s headline digest can reuse the same parsing
    without the data layer importing from the dashboard layer) -- kept as
    a thin alias here under its original name so nothing else in this
    module or its tests needs to change."""
    return extract_headline_title(news_item)


def extract_headlines(news_items: list[dict[str, Any]]) -> list[str]:
    """Titles out of a raw `YFinanceClient.fetch_news()` result, dropping
    any item a title can't be found in."""
    headlines = [_extract_headline(item) for item in news_items]
    return [h for h in headlines if h]


def build_news_prompt(ticker: str, headlines: list[str]) -> list[Any]:
    """Build the `[SystemMessage, HumanMessage]` pair `ChatModel.invoke()`
    expects. Raises `ValueError` for an empty headline list rather than
    sending a prompt with nothing to analyse -- callers should check for
    this case before calling (see `screen_news_sentiment`)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    if not headlines:
        raise ValueError(f"No headlines to analyse for {ticker!r}")
    human = f"Company ticker: {ticker}\n\nHeadlines:\n" + "\n".join(f"- {h}" for h in headlines)
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=human)]


def parse_sentiment_response(raw_text: str) -> dict[str, Any]:
    """Parse the model's reply into `{"summary": str, "investment_grade": float}`.

    Tries a direct JSON parse first (what the prompt asks for); if the
    model wraps the JSON in prose or code fences, falls back to pulling
    out the first `{...}` block. Raises `ValueError` if neither works, so
    the caller can catch it per-ticker rather than letting one malformed
    reply take down a whole batch -- the original's string-splitting had
    no equivalent safeguard.
    """
    text = raw_text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in LLM response: {raw_text!r}")
        parsed = json.loads(match.group(0))

    if "investment_grade" not in parsed or "summary" not in parsed:
        raise ValueError(f"LLM response missing required fields: {parsed!r}")

    grade = float(parsed["investment_grade"])
    grade = max(1.0, min(10.0, grade))  # same clamp behaviour the original applied via grade/10 fallback
    return {"summary": str(parsed["summary"]), "investment_grade": grade}


@dataclass
class NewsSentimentCache:
    """Same-day in-memory cache: at most one LLM call per ticker per
    calendar day.

    A plain dict keyed only by ticker, with the whole cache invalidated
    the first time it's touched on a new day -- simpler than a per-entry
    TTL, and matches how the rest of the dashboard already treats "today's
    data" as one unit (see `Repository.is_data_recent`). Lives for the
    lifetime of the running Dash process only; nothing here is written to
    the database.
    """

    _entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    _as_of: date = field(default_factory=date.today)

    def _roll_if_new_day(self) -> None:
        today = date.today()
        if today != self._as_of:
            self._entries.clear()
            self._as_of = today

    def get(self, ticker: str) -> dict[str, Any] | None:
        self._roll_if_new_day()
        return self._entries.get(ticker)

    def set(self, ticker: str, result: dict[str, Any]) -> None:
        self._roll_if_new_day()
        self._entries[ticker] = result


def analyse_ticker_news(
    ticker: str,
    headlines: list[str],
    llm: ChatModel,
    cache: NewsSentimentCache | None = None,
) -> dict[str, Any]:
    """Get (or compute and cache) the LLM sentiment/grade for one ticker's
    current headlines.

    Returns a dict with `ticker`, `summary`, `investment_grade`, and
    `error` (`None` on success, else a short message) -- callers decide
    whether to show, skip, or retry a failed ticker, rather than one bad
    response raising through the whole batch.
    """
    if cache is not None:
        cached = cache.get(ticker)
        if cached is not None:
            return cached

    try:
        messages = build_news_prompt(ticker, headlines)
        response = llm.invoke(messages)
        parsed = parse_sentiment_response(response.content)
        result = {"ticker": ticker, "error": None, **parsed}
    except Exception as exc:  # one bad ticker must not abort the batch
        logger.warning("News sentiment analysis failed for %s: %s", ticker, exc)
        result = {"ticker": ticker, "error": str(exc), "summary": None, "investment_grade": None}

    if cache is not None:
        cache.set(ticker, result)
    return result


def screen_news_sentiment(
    candidates: list[dict[str, Any]],
    news_by_ticker: dict[str, list[str]],
    llm: ChatModel,
    cache: NewsSentimentCache | None = None,
) -> list[dict[str, Any]]:
    """Run `analyse_ticker_news` for every price-drop candidate and merge
    the result back onto its price-drop info (`reason`, `price_drop_pct`,
    ...).

    Sorted worst-first (highest `investment_grade` = worst outlook), with
    any ticker whose analysis failed or had no headlines available pushed
    to the end rather than dropped -- unlike the original, whose grade was
    computed and then never returned to the caller at all.
    """
    enriched = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        headlines = news_by_ticker.get(ticker, [])
        if not headlines:
            sentiment = {
                "ticker": ticker, "error": "no headlines available",
                "summary": None, "investment_grade": None,
            }
        else:
            sentiment = analyse_ticker_news(ticker, headlines, llm, cache)
        enriched.append({**candidate, **sentiment})

    enriched.sort(key=lambda r: (r["investment_grade"] is None, -(r["investment_grade"] or 0)))
    return enriched
