from __future__ import annotations

import asyncio
import html as html_lib
import re
from typing import Any

import httpx

from ..core import config

DDG_LITE = "https://lite.duckduckgo.com/lite/"
DDG_ANSWER = "https://api.duckduckgo.com/"
TAVILY_URL = "https://api.tavily.com/search"
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKIVOYAGE_API = "https://en.wikivoyage.org/w/api.php"
USER_AGENT = "RihlaTravelAgent/1.0 (educational trip-planning demo; contact: local dev)"
TIMEOUT = httpx.Timeout(12.0)
MAX_SNIPPET = 500


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/").lower()


def _result(title: str, url: str, snippet: str, source: str) -> dict[str, Any]:
    return {"title": title.strip() or url, "url": url.strip(),
            "snippet": (snippet or "").strip()[:MAX_SNIPPET], "source": source}


def _dedup(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for item in results:
        key = _normalize_url(item.get("url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def parse_ddg_lite(page: str, limit: int = 6) -> list[dict[str, Any]]:
    """Parse DuckDuckGo lite result rows into {title, url, snippet} dicts."""
    links = list(re.finditer(
        r"<a[^>]*href=\"([^\"]+)\"[^>]*class='result-link'[^>]*>(.*?)</a>", page, re.S))
    snippets = re.findall(r"class='result-snippet'[^>]*>(.*?)</td>", page, re.S)
    results = []
    for index, match in enumerate(links[:limit]):
        url = html_lib.unescape(match.group(1)).strip()
        title = _strip_tags(match.group(2))
        if not url.startswith("http") or not title:
            continue
        results.append({
            "title": title,
            "url": url,
            "snippet": _strip_tags(snippets[index]) if index < len(snippets) else "",
            "source": "DuckDuckGo",
        })
    return results


async def _ddg_lite(client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
    try:
        resp = await client.post(DDG_LITE, data={"q": query})
        if resp.status_code != 200:
            return []
        return parse_ddg_lite(resp.text, limit)
    except Exception:
        return []


async def _instant_answer(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    try:
        resp = await client.get(DDG_ANSWER, params={
            "q": query, "format": "json", "no_html": 1, "skip_disambig": 1})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    text = (data.get("AbstractText") or "").strip()
    if not text:
        return []
    return [_result(data.get("Heading") or "Instant answer",
                    data.get("AbstractURL") or DDG_ANSWER,
                    text, data.get("AbstractSource") or "DuckDuckGo")]


async def _tavily(client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
    api_key = getattr(config, "TAVILY_API_KEY", "")
    if not api_key:
        return []
    try:
        resp = await client.post(TAVILY_URL, json={
            "api_key": api_key, "query": query, "max_results": limit,
            "include_answer": True, "search_depth": "basic"})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    results = [_result(item.get("title") or "", item.get("url") or "",
                       item.get("content") or "", "Tavily")
               for item in data.get("results") or [] if item.get("url")]
    answer = (data.get("answer") or "").strip()
    if answer:
        results.insert(0, _result("Tavily answer", TAVILY_URL, answer, "Tavily"))
    return results


async def _wiki(client: httpx.AsyncClient, query: str, limit: int, api: str,
                source: str) -> list[dict[str, Any]]:
    try:
        resp = await client.get(api, params={
            "action": "query", "generator": "search", "gsrsearch": query,
            "gsrlimit": limit, "prop": "extracts", "exintro": 1,
            "explaintext": 1, "exchars": MAX_SNIPPET, "format": "json"})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    pages = (data.get("query") or {}).get("pages") or {}
    host = api.split("/w/")[0]
    ranked = sorted(pages.values(), key=lambda p: p.get("index", 99))
    return [_result(page.get("title") or "", f"{host}/wiki/{page.get('title', '').replace(' ', '_')}",
                    page.get("extract") or "", source)
            for page in ranked if page.get("title")]


async def web_search(query: str, limit: int = 6) -> dict[str, Any]:
    """Search the web across several sources. Returns {"results": [...], "error": str | None}.

    Sources are queried in parallel: Tavily (when TAVILY_API_KEY is set), Wikipedia,
    Wikivoyage, DuckDuckGo lite and the DuckDuckGo instant-answer API. Results are
    deduplicated by URL.
    """
    query = (query or "").strip()[:300]
    if not query:
        return {"results": [], "error": "empty query"}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                                 follow_redirects=True) as client:
        groups = await asyncio.gather(
            _tavily(client, query, limit),
            _wiki(client, query, 3, WIKI_API, "Wikipedia"),
            _wiki(client, query, 2, WIKIVOYAGE_API, "Wikivoyage"),
            _ddg_lite(client, query, limit),
            _instant_answer(client, query),
        )
    results = _dedup(item for group in groups for item in group)
    if not results:
        return {"results": [], "error": "no results"}
    return {"results": results[: limit + 2], "error": None}
