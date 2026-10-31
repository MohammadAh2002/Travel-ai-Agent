from __future__ import annotations

import json
import re
import uuid
from datetime import date
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError

from ..agents import (
    advise_documents, advise_lodging, advise_specialist, answer_general, budget_summary, coordinate,
    draft_itinerary, research, verify_itinerary,
)
from ..core.guardrails import inspect_input, safe_reply
from ..core.models import ChatRequest
from ..features.checklist import make_checklist
from ..features.nearby import nearby_places
from ..features.place_info import category_label, short_description
from ..services import watches
from ..services.mcp_client import call_tool, connection
from ..services.memory import get_session, save_session
from .itinerary import (
    closure_hints, collect_sources, estimate_routes, price_conflict_notes, sanitize_itinerary,
    schedule_notes, tool_call, trim_research, verify_costs, verify_selected_hours,
)

DOCS = json.loads((Path(__file__).resolve().parent.parent / "data" / "travel_docs.json").read_text(encoding="utf-8"))

OFF_TOPIC_REPLY = (
    "I'm Rihla, an AI travel-planning assistant — that's the one job I do. I can help with:\n"
    "- Multi-day trip itineraries and one-day plans, with sources, a map and cost estimates\n"
    "- Revising a proposed itinerary\n"
    "- Listed-price checks and nearby places around a pin or Google Maps link\n"
    "- Weather and walking-route questions for your trip\n"
    "- Travel-document guidance from official government sources\n"
    "- Pre-travel checklists, remembering your travel preferences, and hourly weather/currency watches\n\n"
    "What would you like to plan or look up?"
)

GENERAL_FALLBACK = ("I can help plan an itinerary, find nearby places, check travel documents, "
                    "or prepare a pre-trip checklist. What would you like to do?")


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


def specialist_status(names: list[str]) -> list[dict]:
    return [{"name": name, "status": "completed"} for name in names]


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
    costs_known = True
    total_tokens = 0
    agents = []

    def record_usage(usage: dict) -> None:
        nonlocal costs, costs_known, total_tokens
        cost = usage.get("cost_usd")
        if cost is None:
            costs_known = False
        else:
            costs += float(cost)
        total_tokens += int(usage.get("total_tokens") or 0)

    def usage_summary() -> dict:
        return {
            "cost_usd": round(costs, 6) if costs_known else None,
            "cost_known": costs_known,
            "total_tokens": total_tokens,
        }

    try:
        extracted, usage = await coordinate(req.message, state.profile, state.history[:-1])
        record_usage(usage)
        agents.append({"name": "Coordinator", "status": "completed"})
    except Exception as exc:
        if isinstance(exc, APITimeoutError):
            reply = "The planning model timed out after 20 seconds. Please try again."
        elif isinstance(exc, APIStatusError) and exc.status_code == 503:
            reply = "The AI provider is temporarily unavailable (HTTP 503). Please try again shortly."
        elif isinstance(exc, APIStatusError) and exc.status_code == 429:
            reply = "The AI provider rate limit was reached (HTTP 429). Please wait a little and try again."
        elif isinstance(exc, APIStatusError) and exc.status_code in {401, 403}:
            reply = "The AI provider rejected the API key (HTTP error). Check the key in .env."
        elif isinstance(exc, APIStatusError):
            reply = f"The AI provider returned HTTP {exc.status_code}. Please check the model and API settings."
        elif isinstance(exc, APIConnectionError):
            reply = "Couldn't connect to the AI provider. Check your internet connection and try again."
        else:
            reply = str(exc) if isinstance(exc, RuntimeError) else "I couldn't reach the planning model. Please try again."
        return response(reply, state=state.model_dump(), usage=usage_summary())
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
                            usage=usage_summary())
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
            return response(reply, state=state.model_dump(), usage=usage_summary())
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
                                    citations=collect_sources(facts), usage=usage_summary())
                facts = trim_research(facts)
                if state.itinerary and intent == "revise":
                    profile["current_itinerary"] = state.itinerary
                profile["current_request"] = {
                    "message": req.message,
                    "intent": intent,
                    "target_place": extracted.get("target_place"),
                }
                profile["schedule_constraints"] = closure_hints(facts, state.profile.start_date, days)
                draft, usage = await draft_itinerary(profile, facts, days, intent=intent)
                record_usage(usage)
                agents.extend(specialist_status(usage.get("agents_run", [])))
                proposed = {"days": []}
                route_estimates, verified_costs = {}, {}
                for attempt in range(2):
                    await verify_selected_hours(mcp, facts, draft, destination, calls)
                    route_estimates = await estimate_routes(mcp, draft, destination, calls)
                    verified_costs = await verify_costs(mcp, facts, draft, state.profile.currency.upper(),
                                                        int(state.profile.adults or 1), calls)
                    proposed = sanitize_itinerary(draft, facts, profile, days, verified_costs, route_estimates)
                    if len(proposed.get("days", [])) == days or attempt == 1:
                        break
                    profile["current_request"]["repair_note"] = (
                        f"Only {len(proposed['days'])} of the {days} requested days had usable activities. "
                        "Fill every date from start to end with sourced places that are open on that "
                        "weekday, using 24-hour HH:MM times; never schedule a venue on a day it is closed.")
                    draft, usage = await draft_itinerary(profile, facts, days, intent=intent)
                    record_usage(usage)
                    agents.extend(specialist_status(usage.get("agents_run", [])))
                route_notes = []
                if route_estimates:
                    try:
                        route_result, usage = await advise_specialist(
                            "route_mobility_analyst",
                            "Assess these measured route estimates against the traveller's stated mobility and walking preferences. Report evidence-based concerns and uncertainties only.",
                            {"routes": list(route_estimates.values()), "profile": profile},
                        )
                        record_usage(usage)
                        route_notes = route_result.get("caveats", [])
                        agents.append({"name": "Route and Mobility Analyst", "status": "completed"})
                    except Exception:
                        agents.append({"name": "Route and Mobility Analyst", "status": "unavailable"})
                if not proposed.get("days"):
                    found = [item["name"] for item in
                             facts.get("find_attractions", {}).get("attractions", [])
                             if item.get("name")][:5]
                    reply = ("I couldn't build a schedule from the sourced listings this time — the "
                             "places found were closed on those dates or had no reliable times. "
                             + (f"Sourced places I can still work with: {', '.join(found)}. " if found else "")
                             + "Want me to try different dates or a different destination?")
                    state.last_agents = agents
                    state.history.append({"role": "assistant", "content": reply})
                    save_session(state)
                    return response(reply, state=state.model_dump(), tool_calls=calls,
                                    citations=collect_sources(facts), usage=usage_summary())
                try:
                    check, usage = await verify_itinerary(proposed, facts, route_notes)
                    record_usage(usage)
                    agents.extend(specialist_status(usage.get("agents_run", [])))
                except Exception:
                    check = {"approved": False, "issues": [],
                             "note": "the verification step was unavailable"}
                    agents.append({"name": "Independent Itinerary Critic", "status": "unavailable"})
        except Exception as exc:
            reply = f"I couldn't access the trip research tools ({type(exc).__name__}). I won't make up travel facts."
            return response(reply, state=state.model_dump(), tool_calls=calls,
                            usage=usage_summary())
        state.itinerary = proposed
        planned = len(proposed["days"])
        caveats = []
        if planned < days:
            first = date.fromisoformat(state.profile.start_date)
            filled = {day["date"] for day in proposed["days"]}
            missing = [d for d in
                       (first.fromordinal(first.toordinal() + i).isoformat() for i in range(days))
                       if d not in filled]
            caveats.append(f"I could verify sourced activities for {planned} of the {days} requested "
                           f"day(s)" + (f"; nothing verified for {', '.join(missing)}." if missing else "."))
        if not check.get("approved"):
            issues = [str(issue) for issue in (check.get("issues") or [])][:3]
            if not issues and check.get("note"):
                issues = [str(check["note"])]
            caveats.append("The verifier was not fully confident"
                           + (": " + "; ".join(issues) + "." if issues else ".")
                           + " Double-check details before relying on this plan.")
        if facts.get("find_attractions", {}).get("interest_relaxed"):
            caveats.append("Few listings matched your specific interests, so I widened the search to "
                           "other popular sourced places.")
        total_txt = (f"{proposed['estimated_total']} {proposed['currency']}"
                     if proposed["estimated_total"] is not None else "unknown total")
        action_id = "act-" + uuid.uuid4().hex
        pending = {
            "action_id": action_id, "type": "save_trip",
            "summary": f"Save {destination}, {planned} of {days} day(s) planned, estimated {total_txt} "
                       f"for {proposed['travellers']} traveller(s)",
            "payload": {"traveller_id": state.profile.traveller_id,
                        "title": f"{destination}, {planned} day(s)",
                        "itinerary": proposed},
        }
        state.pending_action = pending
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
            stops = ", ".join(
                f"{activity['start_time']} {activity['name']}"
                + (f" ({activity['category']})" if activity.get("category") else "")
                for activity in day["activities"])
            day_lines.append(f"Day {index} ({day['date']}): {stops}.")
        plan_label = f"{days}-day" if planned == days else f"{planned}-day (of {days} requested)"
        reply = (f"Here is a sourced {plan_label} plan for {destination}. Costs are estimates, and each listed "
                 f"place links to its source.{preference_note}{budget_note}"
                 + (" " + " ".join(caveats) if caveats else "")
                 + " Review the itinerary and approve it only if it works for you. Saving stores a plan "
                   "only; nothing is booked or purchased.\n\n" + "\n".join(day_lines))
        sources = (collect_sources(facts) + [citation for cost in verified_costs.values()
                                              for citation in cost.get("citations", []) if citation.get("url")] +
                   [route.get("citation") for route in route_estimates.values()
                    if route.get("citation") and route["citation"].get("url")])
        state.last_sources = sources
        state.last_agents = agents
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), tool_calls=calls, citations=sources,
                        pending=pending, usage=usage_summary())

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
                record_usage(usage)
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
                        usage=usage_summary())

    if intent == "lodging":
        agents.append({"name": "Lodging Advisor", "status": "working"})
        try:
            reply, usage, sources = await advise_lodging(req.message, profile, state.history)
            record_usage(usage)
        except Exception:
            reply = ("I couldn't retrieve live hotel suggestions right now. If you share your "
                     "hotel or area, I can help assess how it may affect your itinerary.")
            sources = []
        agents[-1]["status"] = "completed"
        state.last_agents = agents
        state.last_sources = sources
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), citations=sources,
                        usage=usage_summary())

    if intent == "weather":
        city = state.profile.destination or extracted.get("destination")
        start = state.profile.start_date or extracted.get("start_date")
        if not city or not start:
            reply = "Which destination and travel date should I check for weather?"
            state.history.append({"role": "assistant", "content": reply})
            save_session(state)
            return response(reply, state=state.model_dump(), usage=usage_summary())
        try:
            async with connection() as mcp:
                data = await call_tool(mcp, "get_weather", {
                    "city": city, "start_date": start,
                    "end_date": state.profile.end_date or extracted.get("end_date") or start,
                })
            calls.append(tool_call("get_weather", True, "Weather Analyst"))
        except Exception:
            calls.append(tool_call("get_weather", False, "Weather Analyst"))
            data = None
        if data is None:
            reply = "I couldn't retrieve reliable weather information for those dates, so I won't guess. Please try again later."
            sources = []
        else:
            try:
                result, usage = await advise_specialist(
                    "weather_analyst",
                    "Explain only the supplied weather evidence for the traveller's dates. Distinguish forecast from seasonal normals and say when a forecast is unavailable.",
                    {"destination": city, "start_date": start, "weather": data},
                )
                record_usage(usage)
                reply = result["answer"]
                sources = collect_sources(data)
            except Exception:
                reply = "I couldn't summarize the weather evidence reliably, so I won't guess. Please try again later."
                sources = collect_sources(data)
        agents.append({"name": "Weather Analyst", "status": "completed"})
        state.last_agents = agents
        state.last_sources = sources
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), tool_calls=calls, citations=sources,
                        usage=usage_summary())

    if intent == "route":
        city = state.profile.destination or extracted.get("destination")
        origin = extracted.get("origin") or state.profile.origin
        target = extracted.get("target_place")
        if not city or not origin or not target:
            reply = "Which city and two places should I compare for the route?"
            state.history.append({"role": "assistant", "content": reply})
            save_session(state)
            return response(reply, state=state.model_dump(), usage=usage_summary())
        try:
            async with connection() as mcp:
                route = await call_tool(mcp, "travel_time", {
                    "from_place": str(origin)[:200], "to_place": str(target)[:200],
                    "city": str(city)[:100], "mode": "foot",
                })
            calls.append(tool_call("travel_time", True, "Route and Mobility Analyst"))
        except Exception:
            calls.append(tool_call("travel_time", False, "Route and Mobility Analyst"))
            route = None
        if route is None:
            reply = "I couldn't retrieve a supported walking-route estimate between those places."
            sources = []
        else:
            try:
                result, usage = await advise_specialist(
                    "route_mobility_analyst",
                    "Explain this walking route estimate and its limitations using only the tool result. Do not claim accessibility features that are not reported.",
                    {"route": route, "walking_style": state.profile.walking_style,
                     "max_walk_minutes": (profile.get("saved_preferences") or {}).get("max_walk_minutes")},
                )
                record_usage(usage)
                reply = result["answer"]
                sources = collect_sources(route)
            except Exception:
                reply = "I couldn't summarize the route estimate reliably."
                sources = collect_sources(route)
        agents.append({"name": "Route and Mobility Analyst", "status": "completed"})
        state.last_agents = agents
        state.last_sources = sources
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), tool_calls=calls, citations=sources,
                        usage=usage_summary())

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
                        usage=usage_summary())

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
                    reply = (f"{item['name']} ({category_label(item)}): {raw}. "
                             "This is an estimate from the linked listing, not a live quote.")
                    blurb = short_description(item)
                    if blurb:
                        reply += f"\n{blurb}"
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
                        usage=usage_summary())

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
        return response(reply, state=state.model_dump(), usage=usage_summary())

    if intent == "remember":
        updates = extracted.get("preference_updates") or {}
        allowed = {"budget_style", "interests", "dietary", "walking_tolerance", "max_walk_minutes",
                   "home_currency", "travel_party", "notes"}
        normalized = {}
        for key, value in updates.items():
            if key not in allowed or value is None:
                continue
            if key in {"interests", "dietary"}:
                items = value if isinstance(value, list) else str(value).split(",")
                value = [str(item).strip() for item in items if str(item).strip()]
                if not value:
                    continue
            elif key == "max_walk_minutes":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            else:
                value = str(value)
            if key == "budget_style" and value not in {"budget", "mid-range", "splurge"}:
                continue
            if key == "walking_tolerance" and value not in {"low", "medium", "high"}:
                continue
            normalized[key] = value
        updates = normalized
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

    if intent in {"general", "off_topic"}:
        agents.append({"name": "General Agent", "status": "working"})
        try:
            reply, usage, sources = await answer_general(req.message, state.history)
            record_usage(usage)
        except Exception:
            reply = OFF_TOPIC_REPLY if intent == "off_topic" else GENERAL_FALLBACK
            sources = []
        agents[-1]["status"] = "completed"
        state.last_agents = agents
        state.last_sources = sources
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), citations=sources,
                        usage=usage_summary())

    if intent == "checklist":
        items = make_checklist(state.profile.destination, profile, state.itinerary)
        reply = "Before you travel:\n" + "\n".join(f"- {item}" for item in items)
        agents.append({"name": "Travel Prep Advisor", "status": "completed"})
    else:
        reply = str(extracted.get("question") or GENERAL_FALLBACK)
        agents.append({"name": "Coordinator", "status": "completed"})
    state.last_agents = agents
    state.history.append({"role": "assistant", "content": reply})
    save_session(state)
    return response(reply, state=state.model_dump(), usage=usage_summary())
