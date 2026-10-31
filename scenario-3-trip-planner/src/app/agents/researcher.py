from __future__ import annotations

import re

from ..features.web_search import web_search
from ..services.mcp_client import call_tool


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("ı", "i").replace("İ", "i").lower()).strip()


_PHRASE_TERMS = {
    "cable car": "cable car", "boat ride": "cruise", "boat trip": "cruise", "boat tour": "cruise",
    "turkish bath": "hamam", "grand bazaar": "markets", "princes islands": "islands",
    "prince islands": "islands", "theme park": "theme park", "water park": "water park",
}
_WORD_TERMS = {
    "ship": "cruise", "boat": "cruise", "cruise": "cruise", "ferry": "ferry", "bosphorus": "cruise",
    "telfric": "cable car", "telfrici": "cable car", "teleferik": "cable car",
    "teleferic": "cable car", "teleferici": "cable car", "teleferiki": "cable car",
    "telecabin": "cable car", "gondola": "cable car", "chairlift": "cable car",
    "hamam": "hamam", "hammam": "hamam",
    "shopping": "shopping", "bazaar": "markets", "souvenir": "markets", "souvenirs": "markets",
    "nightlife": "nightlife", "clubbing": "nightlife",
    "beach": "beach", "swimming": "beach",
    "aquarium": "aquarium", "zoo": "zoo",
    "dervish": "whirling dervish", "dervishes": "whirling dervish",
}


def activity_terms(message: str) -> list[str]:
    """Map casual activity requests ('riding ship', 'telfric') to terms the listings can match."""
    text = _fold(message)
    terms = [term for phrase, term in _PHRASE_TERMS.items() if phrase in text]
    for word in re.findall(r"[a-z0-9]+", text):
        term = _WORD_TERMS.get(word)
        if term:
            terms.append(term)
    return list(dict.fromkeys(terms))


_UNSUPPORTED_ACTIVITIES = {
    "sky diving": "sky diving", "skydive": "sky diving", "skydiving": "sky diving",
    "paragliding": "paragliding", "parachute": "sky diving",
    "scuba": "scuba diving", "diving": "sea/scuba diving",
    "snow": "snow activities", "skiing": "skiing", "snowboarding": "snowboarding",
}


def unsupported_activities(message: str) -> list[str]:
    """Adventure activities the traveller asked for that the sourced listings cannot cover."""
    text = _fold(message)
    found = [label for key, label in _UNSUPPORTED_ACTIVITIES.items()
             if re.search(rf"\b{re.escape(key)}", text)]
    return list(dict.fromkeys(found))


_INTEREST_ALIASES = {
    "islamic": "religious", "islami": "religious", "muslim": "religious", "islam": "religious",
    "mosque": "religious", "mosques": "religious",
    "ottoman": "history", "byzantine": "history", "ancient": "history",
}


def normalize_interests(interests: str) -> str:
    """Rewrite casual/misspelled interests ('islami history') into listing tag words ('religious, history')."""
    words = []
    for word in re.findall(r"[a-z0-9]+", _fold(interests)):
        mapped = _INTEREST_ALIASES.get(word, word)
        if mapped not in words:
            words.append(mapped)
    return ", ".join(words)


async def web_activity_ideas(city: str, query_text: str, limit: int = 3) -> list[dict]:
    """Live web search for any experiences the sourced listings do not cover.

    Returns unverified web results ({title, url, snippet}) for whatever the traveller
    asked about — no fixed concept list, the query is built from their own words."""
    query_text = " ".join((query_text or "").replace(",", " ").split())
    query = (f"{query_text} in {city}" if city else query_text).strip()[:300]
    if not query:
        return []
    try:
        data = await web_search(query, limit=limit)
    except Exception:
        return []
    return [item for item in data.get("results", []) if item.get("url")][:limit]


def _merge_attractions(base: dict, rows: list[dict]) -> None:
    target = base.setdefault("attractions", [])
    seen = {item.get("id") or item.get("name") for item in target}
    target += [item for item in rows if (item.get("id") or item.get("name")) not in seen]
    base["count"] = len(target)


async def research(session, city: str, interests: str, start: str | None,
                   end: str | None, extra_queries: list[str] | None = None) -> tuple[dict, list[dict]]:
    results = {}
    calls = []
    requests = [
        ("find_attractions", {"city": city, "interests": interests or None, "limit": 20}),
        ("find_restaurants", {"city": city, "budget": "any", "limit": 12}),
    ]
    if start:
        requests.append(("get_weather", {"city": city, "start_date": start, "end_date": end or start}))
    for tool, args in requests:
        try:
            data = await call_tool(session, tool, args)
            results[tool] = data
            calls.append({"tool": tool, "ok": True, "agent": "Researcher"})
        except Exception as exc:
            results[tool] = {"error": str(exc)}
            calls.append({"tool": tool, "ok": False, "agent": "Researcher"})
    attractions = results.get("find_attractions")
    if interests and isinstance(attractions, dict) and not attractions.get("error") \
            and len(attractions.get("attractions") or []) < 4:
        try:
            wider = await call_tool(session, "find_attractions", {"city": city, "limit": 20})
            calls.append({"tool": "find_attractions", "ok": True, "agent": "Researcher"})
            rows = attractions.get("attractions") or []
            seen = {item.get("id") or item.get("name") for item in rows}
            rows += [item for item in wider.get("attractions", [])
                     if (item.get("id") or item.get("name")) not in seen]
            attractions["attractions"] = rows
            attractions["count"] = len(rows)
            attractions["interest_relaxed"] = True
        except Exception:
            calls.append({"tool": "find_attractions", "ok": False, "agent": "Researcher"})
    for query in extra_queries or []:
        if not query or not query.strip():
            continue
        try:
            extra = await call_tool(session, "find_attractions", {"city": city, "interests": query, "limit": 20})
            calls.append({"tool": "find_attractions", "ok": True, "agent": "Researcher"})
            attractions = results.get("find_attractions")
            if isinstance(attractions, dict) and not attractions.get("error"):
                _merge_attractions(attractions, extra.get("attractions") or [])
        except Exception:
            calls.append({"tool": "find_attractions", "ok": False, "agent": "Researcher"})
    return results, calls
