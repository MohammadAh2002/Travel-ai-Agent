from __future__ import annotations

import math
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

COORDINATES = re.compile(r"(-?\d{1,2}(?:\.\d+)?)\s*[,/]\s*(-?\d{1,3}(?:\.\d+)?)")
ALLOWED_MAP_HOSTS = {"maps.app.goo.gl", "goo.gl", "google.com", "www.google.com", "maps.google.com"}


def coordinates_from_text(value: str) -> tuple[float, float] | None:
    match = COORDINATES.search(value)
    if not match:
        parsed = urlparse(value)
        if parsed.hostname not in ALLOWED_MAP_HOSTS:
            return None
        query = parse_qs(parsed.query)
        for key in ("q", "query", "destination"):
            if query.get(key):
                match = COORDINATES.search(query[key][0])
                if match:
                    break
        if not match:
            match = COORDINATES.search(parsed.path)
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def place_from_map_link(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.hostname not in ALLOWED_MAP_HOSTS:
        return None
    for key in ("q", "query", "destination"):
        value = (parse_qs(parsed.query).get(key) or [None])[0]
        if value and not COORDINATES.search(value):
            return unquote(value).replace("+", " ").strip()
    match = re.search(r"/maps/place/([^/]+)", parsed.path)
    return unquote(match.group(1)).replace("+", " ").strip() if match else None


async def resolve_map_link(value: str) -> tuple[float, float] | None:
    direct = coordinates_from_text(value)
    if direct:
        return direct
    parsed = urlparse(value)
    if parsed.hostname not in ALLOWED_MAP_HOSTS or parsed.scheme not in {"http", "https"}:
        return None
    current = value
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        for _ in range(6):
            response = await client.get(current)
            found = coordinates_from_text(str(response.url))
            if found:
                return found
            if response.status_code not in {301, 302, 303, 307, 308}:
                return coordinates_from_text(response.text[:2000])
            current = urljoin(current, str(response.headers.get("location", "")))
            redirected = urlparse(current)
            if redirected.hostname not in ALLOWED_MAP_HOSTS:
                return None
    return None


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
