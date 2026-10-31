from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from .mcp_client import call_tool, connection

WATCHES: dict[str, dict] = {}


async def refresh(watch: dict) -> dict:
    updates = []
    async with connection() as session:
        if watch.get("currency"):
            try:
                fx = await call_tool(session, "convert_currency", {
                    "amount": 100, "from_currency": watch["currency"], "to_currency": "USD",
                })
                updates.append({"type": "currency", "summary": f"100 {watch['currency']} ≈ "
                               f"{fx.get('converted')} USD", "source_url": fx.get("source_url")})
            except Exception as exc:
                updates.append({"type": "currency", "summary": f"Currency watch unavailable: {exc}"})
        if watch.get("destination") and watch.get("start_date"):
            try:
                weather = await call_tool(session, "get_weather", {
                    "city": watch["destination"], "start_date": watch["start_date"],
                    "end_date": watch.get("end_date") or watch["start_date"],
                })
                updates.append({"type": "weather", "summary": weather.get("note", "Weather checked."),
                                "source_url": weather.get("source_url")})
            except Exception as exc:
                updates.append({"type": "weather", "summary": f"Weather watch unavailable: {exc}"})
    watch["last_checked"] = datetime.now(timezone.utc).isoformat()
    watch["updates"] = updates
    return watch


def add_watch(data: dict) -> dict:
    if sum(item["session_id"] == data["session_id"] for item in WATCHES.values()) >= 10:
        raise ValueError("A session can have at most 10 hourly watches.")
    watch_id = "watch-" + uuid.uuid4().hex[:8]
    watch = {
        "watch_id": watch_id,
        "session_id": data["session_id"],
        "destination": data.get("destination"),
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "currency": data.get("currency"),
        "updates": [],
    }
    WATCHES[watch_id] = watch
    return watch


async def background_loop(interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        for watch in list(WATCHES.values()):
            try:
                await refresh(watch)
            except Exception:
                continue
