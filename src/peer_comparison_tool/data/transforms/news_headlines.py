"""
Headline extraction and dedup -- pure, DB-free.

Moved here from `comparison_tool/news_sentiment.py` (which re-exports
`extract_headline_title`/`extract_headlines` under their original names for
backward compatibility) so `market_conditions.py`'s headline digest can
reuse the same yfinance-news-item parsing without the data layer importing
from the dashboard layer -- `data/` is meant to be usable (and tested)
without anything under `comparison_tool/`, and the reverse dependency
would have inverted that.
"""
from __future__ import annotations

from typing import Any


def extract_headline_title(news_item: dict[str, Any]) -> str | None:
    """Pull a title out of one yfinance news item.

    The original code (`bad_news_trading_model.py`) assumed a flat
    `news['title']` shape. Left as the primary lookup (matches the
    original, unverified against a live `yf.Ticker.get_news()` call in
    this sandbox -- no network access to Yahoo Finance here), with a
    fallback to a `news['content']['title']` shape some yfinance versions
    have used, so an item in either shape is picked up rather than
    silently skipped. Anything matching neither is skipped rather than
    raising, since a malformed single headline shouldn't drop the whole
    ticker/digest from analysis.
    """
    if not isinstance(news_item, dict):
        return None
    if isinstance(news_item.get("title"), str):
        return news_item["title"]
    content = news_item.get("content")
    if isinstance(content, dict) and isinstance(content.get("title"), str):
        return content["title"]
    return None


def extract_headline_link(news_item: dict[str, Any]) -> str | None:
    """Pull a URL out of one yfinance news item, mirroring
    `extract_headline_title`'s two known shapes (flat `link`, or nested
    under `content`) -- optional, only used where a clickable link is
    wanted (the market conditions digest); `None` if neither shape matches."""
    if not isinstance(news_item, dict):
        return None
    if isinstance(news_item.get("link"), str):
        return news_item["link"]
    content = news_item.get("content")
    if isinstance(content, dict):
        canonical = content.get("canonicalUrl")
        if isinstance(canonical, dict) and isinstance(canonical.get("url"), str):
            return canonical["url"]
    return None


def extract_headlines(news_items: list[dict[str, Any]]) -> list[str]:
    """Titles out of a raw `YFinanceClient.fetch_news()` result, dropping
    any item a title can't be found in."""
    headlines = [extract_headline_title(item) for item in news_items]
    return [h for h in headlines if h]


def _normalize_title(title: str) -> str:
    """Case/whitespace-insensitive key for matching the same story
    appearing near-identically across more than one ticker's news feed."""
    return " ".join(title.lower().split())


def dedupe_headlines(news_by_source: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """One entry per unique headline across every source in
    `news_by_source` (e.g. `{"SPY": [...], "^VIX": [...]}`), each with
    `title`, `link` (from whichever source first reported it), `source`
    (that first source), and `also_from` (any other sources that carried
    the same story) -- rather than the same story appearing once per
    benchmark ticker it happened to show up under, which is routine for
    market-wide news (a single Fed announcement will show up in SPY's,
    `^VIX`'s, and `^TNX`'s news feeds alike).

    Order preserved from first appearance; a source's own item order is
    assumed to already be roughly recency-ordered (yfinance's convention),
    not re-sorted here.
    """
    seen: dict[str, dict[str, Any]] = {}
    for source, items in news_by_source.items():
        for item in items:
            title = extract_headline_title(item)
            if not title:
                continue
            key = _normalize_title(title)
            if key not in seen:
                seen[key] = {"title": title, "link": extract_headline_link(item), "source": source, "also_from": []}
            elif source != seen[key]["source"] and source not in seen[key]["also_from"]:
                seen[key]["also_from"].append(source)
    return list(seen.values())
