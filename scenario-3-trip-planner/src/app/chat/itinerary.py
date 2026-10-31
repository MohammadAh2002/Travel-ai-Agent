from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from ..features.place_info import category_label, short_description
from ..services.mcp_client import call_tool


def tool_call(tool: str, ok: bool, agent: str, extra: dict | None = None) -> dict:
    return {"tool": tool, "ok": ok, "agent": agent, **(extra or {})}


def collect_sources(value: Any, out: list[dict] | None = None) -> list[dict]:
    out = out if out is not None else []
    if isinstance(value, dict):
        citation = value.get("citation")
        if isinstance(citation, dict) and citation.get("url"):
            out.append(citation)
        elif value.get("source_url"):
            out.append({"id": value.get("id") or value.get("name") or value.get("source"),
                        "title": value.get("name") or value.get("source") or "Travel data",
                        "url": value["source_url"]})
        for child in value.values():
            if isinstance(child, (dict, list)):
                collect_sources(child, out)
    elif isinstance(value, list):
        for child in value:
            collect_sources(child, out)
    unique = {}
    for item in out:
        if item.get("url"):
            unique[item["url"]] = item
    return list(unique.values())


def trim_research(facts: dict) -> dict:
    trimmed = {}
    for tool_name, data in facts.items():
        if not isinstance(data, dict):
            continue
        trimmed[tool_name] = {k: v for k, v in data.items() if k not in {"note", "retrieved_at"}}
        key = "attractions" if tool_name == "find_attractions" else "restaurants"
        if isinstance(data.get(key), list):
            rows = []
            for item in data[key]:
                if item.get("synthetic"):
                    continue
                rows.append({k: item.get(k) for k in (
                    "id", "name", "alt", "kind", "district", "description", "tags", "hours", "price",
                    "price_sources", "price_conflict", "source_url", "citation", "lat", "lon",
                    "price_tier", "dietary_mentions",
                ) if k in item})
            trimmed[tool_name][key] = rows
    return trimmed


def plan_days(draft: dict) -> list[dict]:
    days = draft.get("days", []) if isinstance(draft, dict) else []
    return [day for day in days if isinstance(day, dict)] if isinstance(days, list) else []


def plan_activities(day: dict) -> list[dict]:
    activities = day.get("activities", [])
    return [item for item in activities if isinstance(item, dict)] if isinstance(activities, list) else []


def known_places(facts: dict) -> dict[str, dict]:
    output = {}
    for field in ("attractions", "restaurants"):
        result = facts.get("find_attractions" if field == "attractions" else "find_restaurants", {})
        rows = result.get(field, []) if isinstance(result, dict) else []
        for item in rows if isinstance(rows, list) else []:
            if not isinstance(item, dict) or item.get("synthetic") or not item.get("name"):
                continue
            output[str(item["name"]).casefold()] = item
    return output


def _fold(text: str) -> str:
    """Lower-case, accent-free text for matching ('Süleymaniye' -> 'suleymaniye')."""
    text = (text or "").replace("ı", "i").replace("İ", "I")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.lower()).strip()


_STOPWORDS = {"the", "of", "and", "in", "at", "a", "an", "de", "di", "el", "al", "to"}


def _tokens(text: str) -> set[str]:
    out = set()
    for token in re.findall(r"[a-z0-9]+", _fold(text)):
        if token in _STOPWORDS:
            continue
        out.add(token[:-1] if len(token) > 4 and token.endswith("s") else token)
    return out


def place_matcher(facts: dict):
    """Resolve a drafted place name to a sourced listing.

    The planner often paraphrases ('Pierre Loti cable car', 'Suleymaniye Mosque');
    matching mirrors the gateway's find_listing: exact name or alt, then substring
    either way, then an unambiguous token-overlap match. Anything else returns None
    so invented places are still dropped."""
    labels = [(item, _fold(label)) for item in known_places(facts).values()
              for label in (item.get("name"), item.get("alt")) if label]

    def match(name: str) -> dict | None:
        query = _fold(re.sub(r",.*$", "", str(name or "")).strip() or str(name or ""))
        if len(query) < 2:
            return None
        for item, label in labels:
            if query == label:
                return item
        for item, label in labels:
            if len(query) >= 4 and query in label:
                return item
        for item, label in labels:
            if len(label) > 4 and re.search(rf"\b{re.escape(label)}\b", query):
                return item
        query_tokens = _tokens(query)
        scored: dict[str, tuple[float, dict]] = {}
        for item, label in labels:
            label_tokens = _tokens(label)
            if not label_tokens or not query_tokens:
                continue
            subset = label_tokens <= query_tokens and (
                len(label_tokens) >= 2 or len(next(iter(label_tokens))) >= 5)
            score = 1.0 if subset else len(query_tokens & label_tokens) / len(query_tokens | label_tokens)
            key = str(item.get("id") or item.get("name"))
            if score >= 0.6 and score > scored.get(key, (0, None))[0]:
                scored[key] = (score, item)
        if scored:
            ranked = sorted(scored.values(), key=lambda entry: -entry[0])
            top = [item for score, item in ranked if score == ranked[0][0]]
            if len(top) == 1:
                return top[0]
        return None

    return match


def schedule_notes(draft: dict, facts: dict, start_date: str, itinerary: dict) -> list[str]:
    resolve = place_matcher(facts)
    kept = {activity["name"].casefold() for day in itinerary.get("days", [])
            for activity in day.get("activities", [])}
    notes = []
    first = date.fromisoformat(start_date)
    for day_index, day in enumerate(plan_days(draft)):
        weekday = first.fromordinal(first.toordinal() + day_index).strftime("%a")
        for activity in plan_activities(day):
            name = str(activity.get("name", ""))
            item = resolve(name)
            if item and weekday in ((item.get("hours") or {}).get("closed_days") or []):
                if item["name"].casefold() in kept:
                    notes.append(f"{name} was moved off {weekday}, when its listing says it is closed.")
                else:
                    notes.append(f"{name} was not scheduled on {weekday}, when its listing says it is closed.")
    return notes


def repeat_notes(draft: dict, facts: dict) -> list[str]:
    """Report venues the draft scheduled on more than one day.

    Sanitizing keeps a sourced place's first day only, so a traveller who asked
    for a return visit sees why the later occurrence is missing."""
    resolve = place_matcher(facts)
    first_day: dict[str, int] = {}
    display: dict[str, str] = {}
    repeated: list[str] = []
    for day_index, day in enumerate(plan_days(draft)):
        seen_today = set()
        for activity in plan_activities(day):
            item = resolve(str(activity.get("name", "")))
            if not item:
                continue
            key = item["name"].casefold()
            display[key] = item["name"]
            if key in seen_today:
                continue
            seen_today.add(key)
            if key in first_day:
                if key not in repeated:
                    repeated.append(key)
            else:
                first_day[key] = day_index
    return [f"{display[key]} was drafted on more than one day; each sourced place is "
            "scheduled once — the later repeat was dropped."
            for key in repeated]


def price_conflict_notes(facts: dict) -> list[str]:
    notes = []
    for name, item in known_places(facts).items():
        sources = item.get("price_sources") or []
        if item.get("price_conflict") and len(sources) > 1:
            prices = " vs ".join(str(source.get("price", {}).get("raw") or "unknown") for source in sources)
            notes.append(f"{item.get('name')}: conflicting listed prices ({prices}); excluded from the total.")
    return notes


def closure_hints(facts: dict, start_date: str, days: int) -> list[str]:
    first = date.fromisoformat(start_date)
    trip_dates = [first.fromordinal(first.toordinal() + index) for index in range(days)]
    hints = []
    for item in known_places(facts).values():
        closed = (item.get("hours") or {}).get("closed_days") or []
        dates = [f"{day.isoformat()} ({day.strftime('%a')})" for day in trip_dates
                 if day.strftime("%a") in closed]
        if dates:
            hints.append(f"{item['name']} is closed on {', '.join(dates)}.")
    return hints


def sanitize_itinerary(draft: dict, facts: dict, profile: dict, days: int, verified_costs: dict,
                       route_estimates: dict | None = None) -> dict:
    resolve = place_matcher(facts)
    start = date.fromisoformat(profile["start_date"]) if profile.get("start_date") else None
    kept_days = []
    total = 0.0
    any_priced = False
    displaced = []
    scheduled = set()
    for day_index, raw_day in enumerate(plan_days(draft)[:days]):
        if not start:
            continue
        planned_date = start.fromordinal(start.toordinal() + day_index).isoformat()
        activities = []
        day_names = set()
        last_end = "00:00"
        for activity in plan_activities(raw_day):
            match = resolve(activity.get("name"))
            if not match or match["name"].casefold() in scheduled:
                continue
            weekday = date.fromisoformat(planned_date).strftime("%a")
            hours = match.get("hours") or {}
            if weekday in (hours.get("closed_days") or []):
                displaced.append({"match": match, "activity": activity, "day_index": day_index,
                                  "date": planned_date})
                continue
            start_time = str(activity.get("start_time") or "09:00")[:5]
            end_time = str(activity.get("end_time") or "10:00")[:5]
            if not re.fullmatch(r"\d{2}:\d{2}", start_time) or not re.fullmatch(r"\d{2}:\d{2}", end_time):
                continue
            travel = (route_estimates or {}).get(
                (day_index, str(activity.get("name", "")).casefold()))
            earliest = (int(last_end[:2]) * 60 + int(last_end[3:]) +
                        int((travel or {}).get("duration_min") or 0))
            starts_at = int(start_time[:2]) * 60 + int(start_time[3:])
            ends_at = int(end_time[:2]) * 60 + int(end_time[3:])
            if starts_at < earliest or ends_at <= starts_at:
                continue
            weekly = (hours.get("weekly") or {}).get(weekday) or []
            if weekly:
                valid_hours = False
                for span in weekly:
                    times = span.split("-", 1)
                    if len(times) == 2 and start_time >= times[0] and end_time <= times[1]:
                        valid_hours = True
                        break
                if not valid_hours:
                    continue
            source = activity.get("source_url")
            if source != match.get("source_url"):
                source = match.get("source_url")
            cost_info = verified_costs.get(match["name"].casefold())
            cost = cost_info.get("party_cost") if cost_info else None
            if isinstance(cost, (int, float)) and cost >= 0:
                total += float(cost)
                any_priced = True
            note = cost_info.get("notes") if cost_info else \
                "No usable price was listed; verify costs before travel."
            if match.get("hours_unverified"):
                note += " Opening hours could not be verified; confirm them before visiting."
            activities.append({
                "name": match["name"],
                "category": category_label(match),
                "description": short_description(match, 220),
                "start_time": start_time,
                "end_time": end_time,
                "estimated_cost": cost,
                "source_url": source,
                "lat": match.get("lat"),
                "lon": match.get("lon"),
                "travel_from_previous_min": (travel or {}).get("duration_min"),
                "route_source_url": (travel or {}).get("source_url"),
                "notes": note[:400],
            })
            day_names.add(match["name"].casefold())
            last_end = end_time
        scheduled |= day_names
        if activities:
            kept_days.append({"date": planned_date, "activities": activities})
    extra_total, extra_priced = relocate_displaced(kept_days, displaced, verified_costs)
    total += extra_total
    any_priced = any_priced or extra_priced
    return {
        "destination": profile.get("destination"),
        "currency": profile.get("currency", "USD").upper(),
        "travellers": int(profile.get("adults") or 1) + max(
            int(profile.get("children_count") or 0), len(profile.get("children_ages") or [])),
        "budget_total": profile.get("budget"),
        "estimated_total": round(total, 2) if any_priced else None,
        "days": kept_days,
        "party_note": profile.get("party_note"),
    }


def _hhmm_minutes(value: str) -> int:
    return int(value[:2]) * 60 + int(value[3:])


def _safe_hhmm(value: str) -> int | None:
    value = str(value or "")[:5]
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        return None
    return int(value[:2]) * 60 + int(value[3:5])


def _weekly_spans(weekly: list[str]) -> list[tuple[int, int]]:
    """Parse 'HH:MM-HH:MM' spans; listings can also carry open ends like '?-20:00', which are skipped."""
    spans = []
    for span in weekly:
        parts = span.split("-", 1)
        if len(parts) != 2:
            continue
        lo, hi = _safe_hhmm(parts[0]), _safe_hhmm(parts[1])
        if lo is not None and hi is not None and hi > lo:
            spans.append((lo, hi))
    return spans


def _day_gaps(activities: list[dict], weekly: list[str], buffer_min: int = 30) -> list[tuple[int, int]]:
    busy = sorted((_hhmm_minutes(a["start_time"]), _hhmm_minutes(a["end_time"])) for a in activities)
    spans = _weekly_spans(weekly) or [(8 * 60, 20 * 60)]
    gaps = []
    for lo, hi in spans:
        cursor = lo
        for start_min, end_min in busy:
            if end_min <= lo or start_min >= hi:
                continue
            if start_min - buffer_min > cursor:
                gaps.append((cursor, start_min - buffer_min))
            cursor = max(cursor, end_min + buffer_min)
        if hi > cursor:
            gaps.append((cursor, hi))
    return gaps


def relocate_displaced(kept_days: list[dict], displaced: list[dict],
                       verified_costs: dict) -> tuple[float, bool]:
    total = 0.0
    any_priced = False
    kept_names = {activity["name"].casefold() for day in kept_days for activity in day["activities"]}
    for item in displaced:
        match, activity = item["match"], item["activity"]
        name = match["name"].casefold()
        if name in kept_names:
            continue
        hours = match.get("hours") or {}
        try:
            duration = max(60, _hhmm_minutes(str(activity.get("end_time") or "10:00")[:5]) -
                           _hhmm_minutes(str(activity.get("start_time") or "09:00")[:5]))
        except (TypeError, ValueError):
            duration = 120
        candidates = sorted(range(len(kept_days)), key=lambda index: abs(index - item["day_index"]))
        placed = None
        longest = (0, None, None)
        for index in candidates:
            day = kept_days[index]
            weekday = date.fromisoformat(day["date"]).strftime("%a")
            if weekday in (hours.get("closed_days") or []):
                continue
            if any(entry["name"].casefold() == name for entry in day["activities"]):
                continue
            for gap_start, gap_end in _day_gaps(day["activities"], (hours.get("weekly") or {}).get(weekday) or []):
                if gap_end - gap_start >= duration:
                    placed = (index, gap_start, gap_start + duration)
                    break
                if gap_end - gap_start > longest[0]:
                    longest = (gap_end - gap_start, index, gap_start)
            if placed:
                break
        if not placed and longest[0] >= 60:
            _, index, gap_start = longest
            placed = (index, gap_start, gap_start + longest[0])
        if not placed:
            continue
        index, start_min, end_min = placed
        day = kept_days[index]
        cost_info = verified_costs.get(name)
        cost = cost_info.get("party_cost") if cost_info else None
        if isinstance(cost, (int, float)) and cost >= 0:
            total += float(cost)
            any_priced = True
        note = cost_info.get("notes") if cost_info else "No usable price was listed; verify costs before travel."
        if match.get("hours_unverified"):
            note += " Opening hours could not be verified; confirm them before visiting."
        entry = {
            "name": match["name"],
            "category": category_label(match),
            "description": short_description(match, 220),
            "start_time": f"{start_min // 60:02d}:{start_min % 60:02d}",
            "end_time": f"{end_min // 60:02d}:{end_min % 60:02d}",
            "estimated_cost": cost,
            "source_url": match.get("source_url"),
            "lat": match.get("lat"),
            "lon": match.get("lon"),
            "travel_from_previous_min": None,
            "route_source_url": None,
            "notes": (f"{note} Rescheduled from {item['date']} because the listing marks the venue closed "
                      f"that day.")[:400],
        }
        day["activities"].append(entry)
        day["activities"].sort(key=lambda entry: entry["start_time"])
        kept_names.add(name)
    return total, any_priced


def _fit_slot(weekly: list[str], earliest: int, duration: int) -> int | None:
    """Earliest start >= earliest where [start, start+duration] fits a listed opening span."""
    spans = _weekly_spans(weekly)
    if not spans:
        return earliest
    for lo, hi in sorted(spans):
        start = max(earliest, lo)
        if start + duration <= hi:
            return start
    return None


def fill_empty_days(proposed: dict, facts: dict, profile: dict, days: int,
                    verified_costs: dict | None = None, draft: dict | None = None) -> list[str]:
    """Backfill trip dates that ended up with no verifiable activities.

    The planner sometimes returns a day it cannot fill from sourced listings (for
    example a requested sky-diving day outside the covered area); sanitizing then
    drops the date entirely. Fill each missing date with unused sourced places
    open that weekday instead of losing the day. Returns the dates that were filled."""
    try:
        first = date.fromisoformat(profile["start_date"])
    except (KeyError, TypeError, ValueError):
        return []
    places = list(known_places(facts).values())
    if not places:
        return []
    itinerary_days = proposed.setdefault("days", [])
    have = {day.get("date") for day in itinerary_days}
    used = {str(activity.get("name", "")).casefold()
            for day in itinerary_days for activity in day.get("activities", [])}
    draft_days = plan_days(draft or {})
    filled = []
    for index in range(days):
        day_date = first.fromordinal(first.toordinal() + index)
        iso = day_date.isoformat()
        if iso in have:
            continue
        weekday = day_date.strftime("%a")
        candidates = []
        for item in places:
            if item.get("kind") in ("eat", "drink"):
                continue
            hours = item.get("hours") or {}
            if weekday in (hours.get("closed_days") or []):
                continue
            if str(item.get("name", "")).casefold() in used:
                continue
            candidates.append(item)
        if not candidates:
            continue
        had_draft = index < len(draft_days) and bool(plan_activities(draft_days[index]))
        if had_draft:  # a planned day whose stops could not be verified: prefer activities and markets
            candidates.sort(key=lambda item: 0 if item.get("kind") in ("do", "buy") else 1)
        activities = []
        cursor = 9 * 60
        for item in candidates:
            if len(activities) >= 3:
                break
            weekly = ((item.get("hours") or {}).get("weekly") or {}).get(weekday) or []
            start_min = _fit_slot(weekly, cursor, 90)
            if start_min is None:
                continue
            end_min = start_min + 90
            cost_info = (verified_costs or {}).get(str(item["name"]).casefold())
            cost = cost_info.get("party_cost") if cost_info else None
            note = cost_info.get("notes") if cost_info else \
                "No converted price estimate is available; verify costs before travel."
            if item.get("hours_unverified"):
                note += " Opening hours could not be verified; confirm them before visiting."
            activities.append({
                "name": item["name"],
                "category": category_label(item),
                "description": short_description(item, 220),
                "start_time": f"{start_min // 60:02d}:{start_min % 60:02d}",
                "end_time": f"{end_min // 60:02d}:{end_min % 60:02d}",
                "estimated_cost": cost if isinstance(cost, (int, float)) and cost >= 0 else None,
                "source_url": item.get("source_url"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "travel_from_previous_min": None,
                "route_source_url": None,
                "notes": (note + " Added to fill the day because the earlier plan for this "
                          "date could not be verified.")[:400],
            })
            used.add(str(item["name"]).casefold())
            cursor = end_min + 45
        if activities:
            itinerary_days.append({"date": iso, "activities": activities})
            filled.append(iso)
    itinerary_days.sort(key=lambda day: day.get("date") or "")
    return filled


async def verify_costs(session, facts: dict, draft: dict, currency: str, adults: int,
                       calls: list[dict]) -> dict[str, dict]:
    resolve = place_matcher(facts)
    names = {
        str(activity.get("name", "")).casefold()
        for day in plan_days(draft)
        for activity in plan_activities(day)
    }
    costs = {}
    for name in names:
        item = resolve(name)
        price = item.get("price") if item else None
        if not isinstance(price, dict) or not price.get("amounts") or price.get("free"):
            continue
        amounts = price.get("amounts", {})
        from_currency = next(iter(amounts), None)
        values = amounts.get(from_currency) or []
        if not from_currency or not values:
            continue
        parsed = []
        fx_sources = []
        for amount in values[:2]:
            try:
                result = await call_tool(session, "convert_currency", {
                    "amount": float(amount), "from_currency": from_currency, "to_currency": currency,
                })
                parsed.append(float(result["converted"]))
                fx_sources.append(result.get("citation") or {})
                calls.append(tool_call("convert_currency", True, "Budget Analyst"))
            except Exception:
                calls.append(tool_call("convert_currency", False, "Budget Analyst"))
                parsed = []
                break
        if not parsed:
            continue
        key = str(item["name"]).casefold()
        if item.get("price_conflict") or len(parsed) > 1 and parsed[0] != parsed[-1]:
            costs[key] = {"party_cost": None, "notes": "Sources disagree about the listed price; confirm it before travel."}
            continue
        adults_count = max(1, adults)
        costs[key] = {
            "party_cost": round(parsed[0] * adults_count, 2),
            "citations": fx_sources,
            "notes": f"Estimate based on a listed price converted to {currency}; adult rates multiplied by "
                     f"{adults_count}; child pricing may differ.",
        }
    return costs


async def verify_selected_hours(session, facts: dict, draft: dict, city: str,
                                calls: list[dict]) -> None:
    resolve = place_matcher(facts)
    names = {
        str(activity.get("name", "")).casefold()
        for day in plan_days(draft)
        for activity in plan_activities(day)
    }
    for name in names:
        item = resolve(name)
        if not item:
            continue
        try:
            result = await call_tool(session, "get_opening_hours", {
                "place_name": item["name"], "city": city,
            })
            if result.get("known"):
                item["hours"] = result.get("hours") or item.get("hours")
                item["source_url"] = item.get("source_url") or result.get("source_url")
            else:
                item["hours"] = None
                item["hours_unverified"] = True
            calls.append(tool_call("get_opening_hours", True, "Researcher"))
        except Exception:
            item["hours"] = None
            item["hours_unverified"] = True
            calls.append(tool_call("get_opening_hours", False, "Researcher"))


async def estimate_routes(session, draft: dict, city: str, calls: list[dict]) -> dict:
    routes = {}
    for day_index, day in enumerate(plan_days(draft)):
        previous = None
        for activity in plan_activities(day):
            name = str(activity.get("name", ""))
            if previous:
                try:
                    result = await call_tool(session, "travel_time", {
                        "from_place": previous, "to_place": name, "city": city, "mode": "foot",
                    })
                    routes[(day_index, name.casefold())] = {
                        "duration_min": result.get("duration_min"),
                        "source_url": result.get("source_url"),
                        "citation": result.get("citation"),
                    }
                    calls.append(tool_call("travel_time", True, "Researcher"))
                except Exception:
                    calls.append(tool_call("travel_time", False, "Researcher"))
            previous = name
    return routes
