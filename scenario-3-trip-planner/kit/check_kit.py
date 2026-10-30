"""Smoke test for the Trip Planner kit: the travel API, its MCP server and one real read.

Start the API first (another terminal):  uvicorn services.travel_api:app --port 8103
Then:                                     python check_kit.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
TOOLS = ["geocode", "find_attractions", "find_restaurants", "get_opening_hours", "get_weather", "convert_currency",
         "travel_time", "save_trip", "list_trips", "get_preferences", "save_preferences"]


def load_env() -> None:
    env = HERE / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def ok(msg: str) -> None:
    print(f"✅ {msg}")


def fail(msg: str, hint: str) -> None:
    print(f"❌ {msg}\n   -> {hint}")
    sys.exit(1)


async def check_mcp(api: str, key: str) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "services.travel_mcp"], cwd=str(HERE),
                                   env={**os.environ, "TRAVEL_API_URL": api, "TRAVEL_API_KEY": key})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = [t.name for t in (await session.list_tools()).tools]
            missing = [t for t in TOOLS if t not in names]
            if missing:
                fail(f"MCP server is missing tools: {missing}", "Use the kit's services/travel_mcp.py unchanged.")
            ok(f"MCP server over stdio lists {len(names)} tools: {', '.join(names)}")
            res = await session.call_tool("get_opening_hours", {"place_name": "Topkapi Palace", "city": "Istanbul"})
            data = res.structuredContent or json.loads(res.content[0].text)
            data = data.get("result", data) if isinstance(data, dict) and "ok" not in data else data
            if not data.get("ok"):
                fail(f"MCP call get_opening_hours failed: {data.get('error')}", "Check TRAVEL_API_URL and TRAVEL_API_KEY.")
            hours = data.get("hours") or {}
            ok(f"MCP call get_opening_hours('Topkapi Palace') -> '{hours.get('raw')}', closed {hours.get('closed_days')} "
               f"[{data.get('mode')}, {data.get('source_url')}]")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_env()
    api = (os.getenv("TRAVEL_API_URL") or "http://localhost:8103").rstrip("/")
    key = os.getenv("TRAVEL_API_KEY") or "dev-key-change-me"
    try:
        health = httpx.get(f"{api}/health", timeout=5).json()
    except Exception as exc:  # noqa: BLE001
        fail(f"Travel API not reachable at {api} ({type(exc).__name__})",
             "Start it: uvicorn services.travel_api:app --port 8103")
    ok(f"Travel API is up at {api} (mode={health.get('mode')}, today={health.get('today')}, "
       f"cached cities={health.get('cached_cities')})")
    if httpx.get(f"{api}/api/attractions", params={"city": "Istanbul"}, timeout=10).status_code != 401:
        fail("The API answered without an API key", "It should return 401; use the kit's services/travel_api.py.")
    ok("Business endpoints reject calls without X-API-Key (401)")
    r = httpx.get(f"{api}/api/attractions", params={"city": "Istanbul", "interest": "history", "limit": 3},
                  headers={"X-API-Key": key}, timeout=60)
    if r.status_code != 200:
        fail(f"GET /api/attractions -> {r.status_code} {r.text[:200]}",
             "Is TRAVEL_API_KEY the same for the API and this script (.env)?")
    data = r.json()
    names = ", ".join(a["name"] for a in data["attractions"])
    ok(f"Read call: {data['count']} Istanbul history attractions ({names}) from {data['source']} [{data['mode']}]")
    asyncio.run(check_mcp(api, key))
    print("✅ Kit ready.")


if __name__ == "__main__":
    main()
