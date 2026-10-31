from __future__ import annotations

from ..services.mcp_client import call_tool


async def research(session, city: str, interests: str, start: str | None,
                   end: str | None) -> tuple[dict, list[dict]]:
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
    return results, calls
