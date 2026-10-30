from __future__ import annotations

import asyncio
import json
import re
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, watches
from .agents import advise_documents, coordinate, draft_itinerary, research, verify_itinerary
from .checklist import make_checklist
from .guardrails import inspect_input, safe_reply
from .memory import get_session, save_session
from .models import ApproveRequest, ChatRequest
from .mcp_client import call_tool, connection
from .nearby import nearby_places
from .voice import transcribe

ROOT = Path(__file__).resolve().parent
DOCS = json.loads((ROOT / "data" / "travel_docs.json").read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(watches.background_loop(config.WATCH_INTERVAL_SECONDS))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Rihla Travel Crew", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
async def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "rihla-trip-planner", "model": config.MODEL,
            "llm_configured": bool(config.OPENROUTER_API_KEY)}


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
                    "id", "name", "kind", "district", "description", "hours", "price", "price_sources",
                    "price_conflict", "source_url", "citation", "lat", "lon", "price_tier", "dietary_mentions",
                ) if k in item})
            trimmed[tool_name][key] = rows
    return trimmed


def plan_days(draft: dict) -> list[dict]:
    days = draft.get("days", []) if isinstance(draft, dict) else []
    return [day for day in days if isinstance(day, dict)] if isinstance(days, list) else []


def plan_activities(day: dict) -> list[dict]:
    activities = day.get("activities", [])
    return [item for item in activities if isinstance(item, dict)] if isinstance(activities, list) else []


def update_profile(profile, extracted: dict) -> None:
    scalar = ("destination", "start_date", "end_date", "adults", "children_count", "budget", "currency",
              "lodging_style", "walking_style", "origin", "gift_heavy", "passport_nationality")
    for field in scalar:
        value = extracted.get(field)
        if value is not None:
            if field in {"adults", "children_count"}:
                try:
                    value = max(0, int(value))
                except (TypeError, ValueError):
                    continue
            elif field == "budget":
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
            elif field in {"start_date", "end_date"}:
                try:
                    date.fromisoformat(str(value))
                except ValueError:
                    continue
                value = str(value)
            elif field == "currency":
                value = str(value).upper()[:3]
            elif field == "gift_heavy":
                value = value if isinstance(value, bool) else str(value).lower() in {"true", "yes", "1"}
            setattr(profile, field, value)
    if extracted.get("children_ages") is not None:
        ages = extracted["children_ages"]
        if isinstance(ages, list):
            profile.children_ages = [int(age) for age in ages if str(age).isdigit() and 0 <= int(age) <= 17]
        profile.children_count = max(profile.children_count, len(profile.children_ages))
    if extracted.get("interests"):
        profile.interests = extracted["interests"] if isinstance(extracted["interests"], list) \
            else [x.strip() for x in str(extracted["interests"]).split(",") if x.strip()]


def missing_trip_info(profile, extracted: dict) -> list[str]:
    missing = []
    if not profile.destination:
        missing.append("Which destination are you visiting?")
    if (not profile.start_date and not extracted.get("days")) or (
            profile.start_date and not profile.end_date and not extracted.get("days")):
        missing.append("What dates are you travelling, or how many days will you be there?")
    if profile.budget is None:
        missing.append("What is your total trip budget and currency?")
    if profile.adults is None:
        missing.append("How many people are travelling, and what are the children's ages (if any)?")
    if profile.children_count and not profile.children_ages:
        missing.append("How old are the children? Their ages help me avoid unsuitable activities.")
    return missing


def trip_days(profile, extracted: dict) -> int:
    if profile.start_date and profile.end_date:
        span = (date.fromisoformat(profile.end_date) - date.fromisoformat(profile.start_date)).days + 1
        if span < 1:
            raise ValueError("The end date must be on or after the start date.")
        return span
    try:
        return max(1, int(extracted.get("days") or 1))
    except (TypeError, ValueError):
        return 1


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


def schedule_notes(draft: dict, facts: dict, start_date: str, itinerary: dict) -> list[str]:
    places = known_places(facts)
    kept = {activity["name"].casefold() for day in itinerary.get("days", [])
            for activity in day.get("activities", [])}
    notes = []
    first = date.fromisoformat(start_date)
    for day_index, day in enumerate(plan_days(draft)):
        weekday = first.fromordinal(first.toordinal() + day_index).strftime("%a")
        for activity in plan_activities(day):
            name = str(activity.get("name", ""))
            item = places.get(name.casefold())
            if item and weekday in ((item.get("hours") or {}).get("closed_days") or []):
                if name.casefold() in kept:
                    notes.append(f"{name} was moved off {weekday}, when its listing says it is closed.")
                else:
                    notes.append(f"{name} was not scheduled on {weekday}, when its listing says it is closed.")
    return notes


def price_conflict_notes(facts: dict) -> list[str]:
    notes = []
    for name, item in known_places(facts).items():
        sources = item.get("price_sources") or []
        if item.get("price_conflict") and len(sources) > 1:
            prices = " vs ".join(str(source.get("price", {}).get("raw") or "unknown") for source in sources)
            notes.append(f"{item.get('name')}: conflicting listed prices ({prices}); excluded from the total.")
    return notes


def sanitize_itinerary(draft: dict, facts: dict, profile: dict, days: int, verified_costs: dict,
                       route_estimates: dict | None = None) -> dict:
    places = known_places(facts)
    start = date.fromisoformat(profile["start_date"]) if profile.get("start_date") else None
    kept_days = []
    total = 0.0
    any_priced = False
    for day_index, raw_day in enumerate(plan_days(draft)[:days]):
        if not start:
            continue
        planned_date = start.fromordinal(start.toordinal() + day_index).isoformat()
        activities = []
        last_end = "00:00"
        last_end = "00:00"
        for activity in plan_activities(raw_day):
            match = places.get(str(activity.get("name", "")).casefold())
            if not match:
                continue
            weekday = date.fromisoformat(planned_date).strftime("%a")
            hours = match.get("hours") or {}
            if weekday in (hours.get("closed_days") or []):
                continue
            start_time = str(activity.get("start_time") or "09:00")[:5]
            end_time = str(activity.get("end_time") or "10:00")[:5]
            if not re.fullmatch(r"\d{2}:\d{2}", start_time) or not re.fullmatch(r"\d{2}:\d{2}", end_time):
                continue
            travel = (route_estimates or {}).get((day_index, match["name"].casefold()))
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
            activities.append({
                "name": match["name"],
                "start_time": start_time,
                "end_time": end_time,
                "estimated_cost": cost,
                "source_url": source,
                "lat": match.get("lat"),
                "lon": match.get("lon"),
                "travel_from_previous_min": (travel or {}).get("duration_min"),
                "route_source_url": (travel or {}).get("source_url"),
                "notes": (cost_info.get("notes") if cost_info else
                          "No usable price was listed; verify costs before travel.")[:400],
            })
            last_end = end_time
        if activities:
            kept_days.append({"date": planned_date, "activities": activities})
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


async def verify_costs(session, facts: dict, draft: dict, currency: str, adults: int,
                       calls: list[dict]) -> dict[str, dict]:
    places = known_places(facts)
    names = {
        str(activity.get("name", "")).casefold()
        for day in plan_days(draft)
        for activity in plan_activities(day)
    }
    costs = {}
    for name in names:
        item = places.get(name)
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
        if item.get("price_conflict") or len(parsed) > 1 and parsed[0] != parsed[-1]:
            costs[name] = {"party_cost": None, "notes": "Sources disagree about the listed price; confirm it before travel."}
            continue
        adults_count = max(1, adults)
        costs[name] = {
            "party_cost": round(parsed[0] * adults_count, 2),
            "citations": fx_sources,
            "notes": f"Estimate based on a listed price converted to {currency}; adult rates multiplied by "
                     f"{adults_count}; child pricing may differ.",
        }
    return costs


async def verify_selected_hours(session, facts: dict, draft: dict, city: str,
                                calls: list[dict]) -> None:
    places = known_places(facts)
    names = {
        str(activity.get("name", "")).casefold()
        for day in plan_days(draft)
        for activity in plan_activities(day)
    }
    unavailable = set()
    for name in names:
        item = places.get(name)
        if not item:
            unavailable.add(name)
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
            calls.append(tool_call("get_opening_hours", True, "Researcher"))
        except Exception:
            unavailable.add(name)
            calls.append(tool_call("get_opening_hours", False, "Researcher"))
    if unavailable:
        for tool_name, field in (("find_attractions", "attractions"), ("find_restaurants", "restaurants")):
            rows = facts.get(tool_name, {}).get(field, [])
            facts[tool_name][field] = [row for row in rows if row.get("name", "").casefold() not in unavailable]


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


def tool_call(tool: str, ok: bool, agent: str, extra: dict | None = None) -> dict:
    return {"tool": tool, "ok": ok, "agent": agent, **(extra or {})}


def response(reply: str, *, state: dict, tool_calls: list[dict] | None = None,
             citations: list[dict] | None = None, pending: dict | None = None,
             result: dict | None = None, usage: dict | None = None) -> dict:
    citations = citations or []
    allowed_urls = {str(item.get("url")) for item in citations if item.get("url")}
    return {
        "reply": safe_reply(reply, allowed_urls),
        "session_id": state["session_id"],
        "state": state,
        "tool_calls": tool_calls or [],
        "citations": citations,
        "pending_action": pending,
        "result": result,
        "usage": usage or {"cost_usd": 0},
        "agents": state.get("last_agents", []),
    }


async def chat_flow(req: ChatRequest) -> dict:
    blocked = inspect_input(req.message)
    state = get_session(req.session_id)
    if blocked:
        return response(blocked, state=state.model_dump())
    if req.user:
        if req.user.get("traveller_id"):
            state.profile.traveller_id = str(req.user["traveller_id"])
        if req.user.get("name"):
            state.profile.party_note = state.profile.party_note or f"Traveller: {req.user['name']}"
    state.history.append({"role": "user", "content": req.message})
    calls: list[dict] = []
    costs = 0.0
    agents = []
    try:
        extracted, usage = await coordinate(req.message, state.profile, state.history[:-1])
        costs += usage.get("cost_usd", 0)
        agents.append({"name": "Coordinator", "status": "completed"})
    except Exception as exc:
        reply = str(exc) if isinstance(exc, RuntimeError) else "I couldn't reach the planning model. Please try again."
        return response(reply, state=state.model_dump(), usage={"cost_usd": costs})
    update_profile(state.profile, extracted)
    intent = extracted.get("intent") or "general"
    profile = state.profile.model_dump()

    if intent in {"itinerary", "day_plan", "revise"}:
        missing = missing_trip_info(state.profile, extracted)
        if missing:
            reply = str(extracted.get("question") or missing[0])
            state.history.append({"role": "assistant", "content": reply})
            state.last_agents = agents
            save_session(state)
            return response(reply, state=state.model_dump(), tool_calls=calls,
                            usage={"cost_usd": round(costs, 6)})
        destination = state.profile.destination
        try:
            days = trip_days(state.profile, extracted)
        except ValueError:
            reply = "The end date must be the same as or later than the start date. Which dates should I use?"
            state.history.append({"role": "assistant", "content": reply})
            state.last_agents = agents
            save_session(state)
            return response(reply, state=state.model_dump())
        if days > 14:
            reply = "I can currently build plans for up to 14 days at a time. Which 14-day window should I focus on?"
            state.history.append({"role": "assistant", "content": reply})
            state.last_agents = agents
            save_session(state)
            return response(reply, state=state.model_dump())
        if not state.profile.start_date:
            reply = "Please give me the first travel date so I can check opening days and build the itinerary."
            state.history.append({"role": "assistant", "content": reply})
            state.last_agents = agents
            save_session(state)
            return response(reply, state=state.model_dump(), usage={"cost_usd": round(costs, 6)})
        try:
            async with connection() as mcp:
                if state.profile.traveller_id != "TRV-GUEST":
                    try:
                        prefs = await call_tool(mcp, "get_preferences",
                                                {"traveller_id": state.profile.traveller_id})
                        calls.append(tool_call("get_preferences", True, "Researcher"))
                        saved = prefs.get("preferences", {})
                        if saved:
                            profile["saved_preferences"] = saved
                            state.profile.interests = state.profile.interests or saved.get("interests", [])
                            profile["saved_preferences"] = saved
                            if saved.get("dietary"):
                                profile["saved_dietary"] = saved["dietary"]
                    except Exception:
                        calls.append(tool_call("get_preferences", False, "Researcher"))
                facts, research_calls = await research(mcp, destination, ", ".join(
                    state.profile.interests or extracted.get("interests") or []), state.profile.start_date,
                    state.profile.end_date)
                calls.extend(research_calls)
                agents.append({"name": "Researcher", "status": "completed"})
                attraction_result = facts.get("find_attractions", {})
                if attraction_result.get("error"):
                    reply = ("I couldn't access the attraction data right now, so I won't invent places or propose "
                             "a plan. Please try again later.")
                    state.last_agents = agents + [{"name": "Verifier", "status": "blocked"}]
                    state.history.append({"role": "assistant", "content": reply})
                    save_session(state)
                    return response(reply, state=state.model_dump(), tool_calls=calls,
                                    citations=collect_sources(facts), usage={"cost_usd": round(costs, 6)})
                facts = trim_research(facts)
                if state.itinerary and intent == "revise":
                    profile["current_itinerary"] = state.itinerary
                draft, usage = await draft_itinerary(profile, facts, days)
                costs += usage.get("cost_usd", 0)
                agents.append({"name": "Itinerary Planner", "status": "completed"})
                await verify_selected_hours(mcp, facts, draft, destination, calls)
                route_estimates = await estimate_routes(mcp, draft, destination, calls)
                verified_costs = await verify_costs(mcp, facts, draft, state.profile.currency.upper(),
                                                    int(state.profile.adults or 1), calls)
                proposed = sanitize_itinerary(draft, facts, profile, days, verified_costs, route_estimates)
                check, usage = await verify_itinerary(proposed, facts)
                costs += usage.get("cost_usd", 0)
                agents.append({"name": "Verifier", "status": "completed"})
                if not check.get("approved") or len(proposed.get("days", [])) != days:
                    reply = "I couldn't verify enough sourced activities to propose a reliable itinerary. Please adjust the request or try another date."
                    state.last_agents = agents
                    state.history.append({"role": "assistant", "content": reply})
                    save_session(state)
                    return response(reply, state=state.model_dump(), tool_calls=calls,
                                    citations=collect_sources(facts), usage={"cost_usd": round(costs, 6)})
        except Exception as exc:
            reply = f"I couldn't access the trip research tools ({type(exc).__name__}). I won't make up travel facts."
            return response(reply, state=state.model_dump(), tool_calls=calls,
                            usage={"cost_usd": round(costs, 6)})
        state.itinerary = proposed
        action_id = "act-" + uuid.uuid4().hex
        pending = {
            "action_id": action_id, "type": "save_trip",
            "summary": f"Save {destination}, {days} day(s), estimated {proposed['estimated_total']} "
                       f"{proposed['currency']} for {proposed['travellers']} traveller(s)",
            "payload": {"traveller_id": state.profile.traveller_id, "title": f"{destination}, {days} day(s)",
                        "itinerary": proposed},
        }
        state.pending_action = pending
        total = proposed["estimated_total"]
        budget = proposed.get("budget_total")
        budget_note = " " + budget_summary(proposed)
        conflict_notes = price_conflict_notes(facts)
        if conflict_notes:
            budget_note += " " + " ".join(conflict_notes)
        closure_notes = schedule_notes(draft, facts, state.profile.start_date, proposed)
        if closure_notes:
            budget_note += " " + " ".join(closure_notes)
        preference_note = (f" I used your saved preferences: {', '.join(profile.get('saved_dietary', []))}."
                           if profile.get("saved_dietary") else "")
        day_lines = []
        for index, day in enumerate(proposed["days"], 1):
            stops = ", ".join(f"{activity['start_time']} {activity['name']}" for activity in day["activities"])
            day_lines.append(f"Day {index} ({day['date']}): {stops}.")
        reply = (f"Here is a sourced {days}-day plan for {destination}. Costs are estimates, and each listed "
                 f"place links to its source.{preference_note}{budget_note} Review the itinerary and approve it only if it works "
                 "for you. Saving stores a plan only; nothing is booked or purchased.\n\n" + "\n".join(day_lines))
        sources = (collect_sources(facts) + [citation for cost in verified_costs.values()
                                              for citation in cost.get("citations", []) if citation.get("url")] +
                   [route.get("citation") for route in route_estimates.values()
                    if route.get("citation") and route["citation"].get("url")])
        state.last_sources = sources
        state.last_agents = agents
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), tool_calls=calls, citations=sources,
                        pending=pending, usage={"cost_usd": round(costs, 6)})

    if intent == "documents":
        destination = state.profile.destination or extracted.get("destination")
        refs = [item for item in DOCS if destination and
                (destination.casefold() in item["destination"].casefold() or
                 item["destination"] == "Schengen Area" and destination.casefold() in
                 {"france", "spain", "italy", "germany", "netherlands", "greece"})]
        nationality = extracted.get("passport_nationality") or state.profile.passport_nationality
        agents.append({"name": "Documents Advisor", "status": "working"})
        if not destination:
            reply = "Which country are you travelling to, and what passport nationality will you travel on? Entry rules depend on both."
        elif not nationality:
            reply = (f"What passport nationality will you travel on? Entry requirements for {destination} depend on it. "
                     "I’ll use official government guidance only.")
        else:
            try:
                reply, usage = await advise_documents(req.message, nationality, destination, refs)
                costs += usage.get("cost_usd", 0)
            except Exception as exc:
                reply = f"I couldn't check official document guidance ({type(exc).__name__}). Please contact the destination embassy or consulate by phone or email to confirm."
        agents[-1]["status"] = "completed"
        if refs:
            reply += "\n\nOfficial government references:\n" + "\n".join(
                f"- [{item['source_name']}]({item['url']})" for item in refs)
        sources = refs
        state.last_agents = agents
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), citations=sources,
                        usage={"cost_usd": round(costs, 6)})

    if intent == "nearby":
        place_text = extracted.get("origin") or req.message
        try:
            async with connection() as mcp:
                reply, places, calls = await nearby_places(mcp, place_text, int(extracted.get("minutes") or 15))
        except Exception as exc:
            reply, places, calls = f"I couldn't query nearby listings ({type(exc).__name__}).", [], []
        agents.append({"name": "Nearby Guide", "status": "completed"})
        sources = collect_sources(places)
        state.last_agents = agents
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), tool_calls=calls, citations=sources,
                        usage={"cost_usd": round(costs, 6)})

    if intent == "price":
        destination = state.profile.destination or extracted.get("destination")
        if not destination:
            reply = "Which city and place are you asking about? If you share a destination, I can check the listed price and show any disagreement between sources."
            state.last_agents = agents
            state.history.append({"role": "assistant", "content": reply})
            save_session(state)
            return response(reply, state=state.model_dump())
        query = str(extracted.get("target_place") or
                    (", ".join(state.profile.interests) if state.profile.interests else req.message))
        try:
            async with connection() as mcp:
                data = await call_tool(mcp, "find_attractions", {"city": destination, "interests": query, "limit": 10})
            calls.append(tool_call("find_attractions", True, "Researcher"))
            candidates = [place for place in data.get("attractions", []) if not place.get("synthetic")]
            tokens = [token.casefold() for token in re.findall(r"[A-Za-zÀ-ÿ0-9]+", query) if len(token) > 3]
            item = max(candidates, key=lambda place: sum(token in place.get("name", "").casefold() for token in tokens),
                       default=None)
            if not item:
                reply = "I couldn't find a matching place in the available listings, so I can't verify its price."
            else:
                price_sources = item.get("price_sources") or []
                if len(price_sources) > 1:
                    details = " / ".join(str(source.get("price", {}).get("raw") or "price unavailable")
                                         for source in price_sources)
                    reply = (f"The listed sources disagree for {item['name']}: {details}. The second entry may be "
                             "synthetic test data in this demo; treat all prices as estimates and confirm with the venue.")
                else:
                    raw = (item.get("price") or {}).get("raw") or "No listed price"
                    reply = f"{item['name']}: {raw}. This is an estimate from the linked listing, not a live quote."
            agents.append({"name": "Researcher", "status": "completed"})
            sources = collect_sources(data)
        except Exception as exc:
            reply = f"I couldn't load the price listing ({type(exc).__name__}); I won't guess."
            sources = []
        state.last_agents = agents
        state.last_sources = sources
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), tool_calls=calls, citations=sources,
                        usage={"cost_usd": round(costs, 6)})

    if intent == "watch":
        watch = watches.add_watch({
            "session_id": state.session_id,
            "destination": state.profile.destination or extracted.get("destination"),
            "start_date": state.profile.start_date or extracted.get("start_date"),
            "end_date": state.profile.end_date or extracted.get("end_date"),
            "currency": state.profile.currency,
        })
        try:
            await watches.refresh(watch)
        except Exception:
            pass
        reply = ("I've started an hourly watch for available weather and currency updates. Hotel prices and flight "
                 "availability aren't provided by this trip data service, so I can't monitor those.")
        agents.append({"name": "Trip Watch", "status": "completed"})
        state.last_agents = agents
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), usage={"cost_usd": round(costs, 6)})

    if intent == "remember":
        updates = extracted.get("preference_updates") or {}
        allowed = {"budget_style", "interests", "dietary", "walking_tolerance", "max_walk_minutes",
                   "home_currency", "travel_party", "notes"}
        updates = {key: value for key, value in updates.items() if key in allowed and value is not None}
        if not updates:
            reply = "What lasting travel preference would you like me to remember (for example, a diet, interests, or walking limit)?"
            state.history.append({"role": "assistant", "content": reply})
            save_session(state)
            return response(reply, state=state.model_dump())
        pending = {
            "action_id": "act-" + uuid.uuid4().hex,
            "type": "save_preferences",
            "summary": "Save these travel preferences for future trips: " + ", ".join(updates),
            "payload": {"traveller_id": state.profile.traveller_id, "preferences": updates},
        }
        state.pending_action = pending
        reply = f"I can remember {', '.join(updates)} for future trips. Please approve to save these preferences."
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), pending=pending)

    if intent == "checklist":
        items = make_checklist(state.profile.destination, profile, state.itinerary)
        reply = "Before you travel:\n" + "\n".join(f"- {item}" for item in items)
        agents.append({"name": "Travel Prep Advisor", "status": "completed"})
    else:
        reply = str(extracted.get("question") or "I can help plan an itinerary, find nearby places, check travel documents, or prepare a pre-trip checklist. What would you like to do?")
        agents.append({"name": "Coordinator", "status": "completed"})
    state.last_agents = agents
    state.history.append({"role": "assistant", "content": reply})
    save_session(state)
    return response(reply, state=state.model_dump(), usage={"cost_usd": round(costs, 6)})


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=422, detail="message cannot be empty")
    return await chat_flow(req)


@app.post("/api/approve")
async def approve(req: ApproveRequest):
    state = get_session(req.session_id)
    action = state.pending_action
    if not action or action.get("action_id") != req.action_id:
        prior = state.completed_actions.get(req.action_id)
        if prior:
            return response(prior["reply"], state=state.model_dump(), result=prior["result"],
                            citations=state.last_sources)
        raise HTTPException(status_code=409, detail="No matching pending action. It may have expired or been replaced.")
    if not req.approved:
        state.pending_action = None
        reply = "Rejected. Nothing was saved, booked, reserved, or paid."
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), result=None)
    try:
        async with connection() as mcp:
            if action.get("type") == "save_preferences":
                result = await call_tool(mcp, "save_preferences", action["payload"])
                result_id = "preferences updated"
                tool = "save_preferences"
            else:
                result = await call_tool(mcp, "save_trip", {
                    **action["payload"], "idempotency_key": action["action_id"],
                })
                result_id = result.get("trip_id")
                tool = "save_trip"
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not save the approved plan: {type(exc).__name__}") from exc
    state.pending_action = None
    reply = (f"Saved as {result_id}. Nothing was booked, reserved, or paid."
             if tool == "save_trip" else "Your preferences are saved for future trip planning.")
    state.history.append({"role": "assistant", "content": reply})
    result_data = {"trip_id": result_id} if tool == "save_trip" else {"preferences_saved": True}
    state.completed_actions[req.action_id] = {"reply": reply, "result": result_data}
    save_session(state)
    return response(reply, state=state.model_dump(), result=result_data,
                    tool_calls=[tool_call(tool, True, "Approval Gate")], citations=state.last_sources)


@app.post("/api/voice")
async def voice(session_id: str = Form(...), audio: UploadFile = File(...),
                traveller_id: str | None = Form(None)):
    payload = await audio.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file must be under 20 MB.")
    try:
        text = await asyncio.to_thread(transcribe, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail="The audio could not be decoded. Try recording again.") from exc
    if not text:
        raise HTTPException(status_code=422, detail="No speech was detected.")
    user = {"traveller_id": traveller_id} if traveller_id else None
    result = await chat_flow(ChatRequest(session_id=session_id, message=text, user=user))
    result["transcript"] = text
    return result


@app.post("/api/watch")
async def create_watch(data: dict):
    if not data.get("session_id"):
        raise HTTPException(status_code=422, detail="session_id is required")
    try:
        watch = watches.add_watch(data)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    try:
        await watches.refresh(watch)
    except Exception:
        pass
    return watch


@app.get("/api/watch/{session_id}")
async def get_watches(session_id: str):
    return {"watches": [item for item in watches.WATCHES.values() if item["session_id"] == session_id]}


@app.delete("/api/watch/{watch_id}")
async def delete_watch(watch_id: str):
    watch = watches.WATCHES.pop(watch_id, None)
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")
    return {"deleted": watch_id}
