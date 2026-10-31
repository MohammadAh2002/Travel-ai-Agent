from __future__ import annotations

import html as html_lib
import re
from typing import Any

import httpx

DDG_LITE = "https://lite.duckduckgo.com/lite/"
DDG_ANSWER = "https://api.duckduckgo.com/"
USER_AGENT = "RihlaTravelAgent/1.0 (educational trip-planning demo; contact: local dev)"
TIMEOUT = httpx.Timeout(12.0)


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


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


async def _instant_answer(client: httpx.AsyncClient, query: str) -> dict[str, Any] | None:
    try:
        resp = await client.get(DDG_ANSWER, params={
            "q": query, "format": "json", "no_html": 1, "skip_disambig": 1})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    text = (data.get("AbstractText") or "").strip()
    if not text:
        return None
    return {"title": data.get("Heading") or "Instant answer",
            "url": data.get("AbstractURL") or DDG_ANSWER,
            "snippet": text, "source": data.get("AbstractSource") or "DuckDuckGo"}


async def web_search(query: str, limit: int = 6) -> dict[str, Any]:
    """Search the public web for a query. Returns {"results": [...], "error": str | None}."""
    query = (query or "").strip()[:300]
    if not query:
        return {"results": [], "error": "empty query"}
    results: list[dict[str, Any]] = []
    error: str | None = None
    lite_html = None
    answer = None
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                                 follow_redirects=True) as client:
        try:
            lite = await client.post(DDG_LITE, data={"q": query})
            if lite.status_code == 200:
                lite_html = lite.text
            else:
                error = f"search engine returned HTTP {lite.status_code}"
        except Exception as exc:
            error = type(exc).__name__
        answer = await _instant_answer(client, query)
    if lite_html:
        results = parse_ddg_lite(lite_html, limit)
    if answer:
        results.insert(0, answer)
    if not results:
        return {"results": [], "error": error or "no results"}
    return {"results": results[: limit + 1], "error": None}
