from __future__ import annotations

from ..mcp_client import call_tool


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
    return results, calls
