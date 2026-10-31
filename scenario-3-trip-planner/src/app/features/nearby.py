from __future__ import annotations

from .map_tools import haversine_km, place_from_map_link, resolve_map_link
from ..services.mcp_client import call_tool


async def nearby_places(session, text: str, minutes: int = 15) -> tuple[str, list[dict], list[dict]]:
    calls = []
    coords = await resolve_map_link(text)
    if not coords:
        try:
            resolved = await call_tool(session, "geocode", {"place": place_from_map_link(text) or text})
            coords = (float(resolved["lat"]), float(resolved["lon"]))
            calls.append({"tool": "geocode", "ok": True, "agent": "Nearby Guide"})
        except Exception as exc:
            calls.append({"tool": "geocode", "ok": False, "agent": "Nearby Guide"})
            return (f"I couldn't resolve that Google Maps link or place from available map data ({exc}). "
                    "Paste a pin link containing coordinates, or give me a place name and city."), [], calls
    city = None
    try:
        geocoded = await call_tool(session, "geocode", {"place": f"{coords[0]},{coords[1]}"})
        city = geocoded.get("city")
        calls.append({"tool": "geocode", "ok": True, "agent": "Nearby Guide"})
    except Exception:
        calls.append({"tool": "geocode", "ok": False, "agent": "Nearby Guide"})
    if not city:
        nearest = (float("inf"), None)
        for candidate in ("Istanbul", "Amman"):
            try:
                city_pin = await call_tool(session, "geocode", {"place": candidate})
                calls.append({"tool": "geocode", "ok": True, "agent": "Nearby Guide"})
                distance = haversine_km(coords, (float(city_pin["lat"]), float(city_pin["lon"])))
                if distance < nearest[0]:
                    nearest = (distance, city_pin.get("city") or candidate)
            except Exception:
                calls.append({"tool": "geocode", "ok": False, "agent": "Nearby Guide"})
                continue
        if nearest[0] <= 100:
            city = nearest[1]
    if not city:
        return "I found the coordinates, but don't have nearby place listings for that area in the available data.", [], calls
    if "pharm" in text.casefold():
        maps_url = f"https://www.google.com/maps/search/pharmacy/@{coords[0]},{coords[1]},15z"
        reply = ("The travel data doesn't include pharmacy listings, so I can't verify nearby pharmacies. "
                 f"[Search pharmacies near this pin on Google Maps]({maps_url}) and confirm opening hours directly.")
        return reply, [{"citation": {"id": "google-maps-pharmacy-search", "title": "Google Maps pharmacy search",
                                    "url": maps_url}}], calls
    results = []
    for name, args, field in (
        ("find_attractions", {"city": city, "interests": None, "limit": 30}, "attractions"),
        ("find_restaurants", {"city": city, "budget": "any", "limit": 20}, "restaurants"),
    ):
        try:
            data = await call_tool(session, name, args)
            calls.append({"tool": name, "ok": True, "agent": "Nearby Guide"})
            for place in data.get(field, []):
                if place.get("lat") is None or place.get("lon") is None:
                    continue
                distance = haversine_km(coords, (float(place["lat"]), float(place["lon"])))
                walk_minutes = round(distance / 4.2 * 60)
                if walk_minutes <= max(1, min(minutes, 120)):
                    results.append({**place, "distance_km": round(distance, 2),
                                    "walk_minutes_estimate": walk_minutes})
        except Exception:
            calls.append({"tool": name, "ok": False, "agent": "Nearby Guide"})
    results.sort(key=lambda row: row["walk_minutes_estimate"])
    if not results:
        return (f"I couldn't find listed places within an estimated {minutes}-minute walk in the available "
                f"{city} data. Walking times are straight-line estimates, not routed directions."), [], calls
    lines = [f"Near your pin in {city} (straight-line walking-time estimates; check a live map for actual routes):"]
    for place in results[:8]:
        lines.append(f"- **{place['name']}** — about {place['walk_minutes_estimate']} min / "
                     f"{place['distance_km']} km; [source]({place.get('source_url')})")
    return "\n".join(lines), results, calls
