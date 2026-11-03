from __future__ import annotations

import json
import re
import uuid
from datetime import date
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError

from ..agents import (
    activity_terms, advise_documents, advise_flight, advise_lodging, advise_specialist, answer_general,
    budget_summary, coordinate, draft_itinerary, normalize_interests, research, unsupported_activities,
    verify_itinerary, web_activity_ideas,
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
    closure_hints, collect_sources, estimate_routes, fill_empty_days, price_conflict_notes,
    repeat_notes, sanitize_itinerary, schedule_notes, tool_call, trim_research, verify_costs,
    verify_selected_hours,
)

DOCS = json.loads((Path(__file__).resolve().parent.parent / "data" / "travel_docs.json").read_text(encoding="utf-8"))

OFF_TOPIC_REPLY = (
    "I'm Rihla, an AI travel assistant. I can help with:\n"
    "- Multi-day trip itineraries and one-day plans, with sources, a map and cost estimates\n"
    "- Revising a proposed itinerary\n"
    "- Listed-price checks and nearby places around a pin or Google Maps link\n"
    "- Weather and walking-route questions for your trip\n"
    "- Hotel suggestions matched to your preferences (stars, meals, budget) from live web search\n"
    "- Flight and baggage advice (how many bags, weight, morning vs night flights)\n"
    "- Travel-document guidance from official government sources\n"
    "- Pre-travel checklists, remembering your travel preferences, and hourly weather/currency watches\n"
    "- And general questions — I'll answer freely and search the live web when it helps\n\n"
    "What would you like to plan or look up?"
)

GENERAL_FALLBACK = ("I can help plan an itinerary, find nearby places, check travel documents, "
                    "or prepare a pre-trip checklist. What would you like to do?")


def _preferences_not_found(exc: BaseException) -> bool:
    # MCP's async task groups wrap tool errors, sometimes more than once.
    if isinstance(exc, BaseExceptionGroup):
        return all(_preferences_not_found(child) for child in exc.exceptions)
    return isinstance(exc, RuntimeError) and str(exc).startswith("traveller_not_found:")


def update_profile(profile, extracted: dict, merge_interests: bool = False) -> None:
    scalar = ("destination", "start_date", "end_date", "adults", "children_count", "budget", "currency",
              "lodging_style", "walking_style", "origin", "gift_heavy", "passport_nationality",
              "hotel_stars", "hotel_board", "hotel_budget", "hotel_area",
              "flight_bags", "flight_bag_kg", "flight_time_pref")
    for field in scalar:
        value = extracted.get(field)
        if value is not None:
            if field in {"adults", "children_count", "hotel_stars", "flight_bags"}:
                try:
                    value = max(0, int(value))
                except (TypeError, ValueError):
                    continue
            elif field in {"budget", "hotel_budget", "flight_bag_kg"}:
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
        interests = extracted["interests"] if isinstance(extracted["interests"], list) \
            else [x.strip() for x in str(extracted["interests"]).split(",") if x.strip()]
        if merge_interests:
            profile.interests = list(dict.fromkeys([*profile.interests, *interests]))
        else:
            profile.interests = interests


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

    # Common memory questions should work without an LLM or web search.
    memory_question = bool(re.fullmatch(
        r"(?:what (?:do you know|do you remember|have you saved) about me|"
        r"(?:show|list)(?: me)? my (?:saved |travel )?preferences|"
        r"what are my (?:saved |travel )?preferences|"
        r"(?:شو|ماذا|ايش|إيش) (?:بتعرف|بتتذكر|بتتذكره|تعرف|تتذكر) عني|"
        r"(?:اعرض|ورجيني) تفضيلاتي(?: المحفوظة)?)",
        req.message.strip().rstrip("?؟!. ").lower(),
    ))
    try:
        if memory_question:
            extracted, usage = {"intent": "recall_preferences"}, {"cost_usd": 0}
        else:
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
    intent = extracted.get("intent") or "general"
    if intent == "recall_preferences":
        saved = {}
        failed = False
        if state.profile.traveller_id != "TRV-GUEST":
            try:
                async with connection() as mcp:
                    result = await call_tool(mcp, "get_preferences", {"traveller_id": state.profile.traveller_id})
                saved = result.get("preferences", {})
                calls.append(tool_call("get_preferences", True, "Preference Memory"))
            except Exception as exc:
                failed = not _preferences_not_found(exc)
                calls.append(tool_call("get_preferences", not failed, "Preference Memory"))
        if failed:
            reply = "I couldn't load your saved preferences right now. Please try again."
        elif saved:
            labels = {"dietary": "Dietary preferences", "interests": "Interests",
                      "budget_style": "Budget style", "walking_tolerance": "Walking tolerance",
                      "max_walk_minutes": "Maximum walking minutes", "home_currency": "Home currency",
                      "travel_party": "Travel party", "notes": "Notes"}
            rows = [f"- {labels.get(key, key)}: {', '.join(map(str, value)) if isinstance(value, list) else value}"
                    for key, value in saved.items()]
            reply = "Here are your saved travel preferences:\n" + "\n".join(rows)
        else:
            reply = "You don't have any saved travel preferences yet. Tell me what to remember, then approve saving it."
        state.history.append({"role": "assistant", "content": reply})
        state.last_agents = [{"name": "Preference Memory", "status": "failed" if failed else "completed"}]
        state.last_sources = []
        save_session(state)
        return response(reply, state=state.model_dump(), tool_calls=calls, usage=usage_summary())
    update_profile(state.profile, extracted, merge_interests=(intent == "revise"))
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
        recent_user_text = " ".join(
            m["content"] for m in state.history if m.get("role") == "user")[-600:]
        terms = activity_terms(recent_user_text)
        unsupported = unsupported_activities(recent_user_text)
        auto_note = ""
        if state.profile.start_date and state.profile.end_date:
            span = (date.fromisoformat(state.profile.end_date) -
                    date.fromisoformat(state.profile.start_date)).days + 1
            try:
                requested = int(extracted.get("days") or 0)
            except (TypeError, ValueError):
                requested = 0
            if 1 <= span < requested <= 14:
                first = date.fromisoformat(state.profile.start_date)
                state.profile.end_date = first.fromordinal(first.toordinal() + requested - 1).isoformat()
                profile = state.profile.model_dump()
                auto_note = (f"You asked for {requested} days but your dates covered only {span}, so I "
                             f"planned {requested} days starting {state.profile.start_date} "
                             f"(say \"use only my dates\" to shorten it).")
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
        if (intent in {"itinerary", "day_plan"} and not state.itinerary
                and not state.profile.style_asked
                and not state.profile.interests and not extracted.get("interests")
                and not extracted.get("target_place") and not activity_terms(req.message)
                and "saved preferenc" not in req.message.casefold()):
            state.profile.style_asked = True
            reply = str(extracted.get("question") or (
                "Before I draft it: do you want activity-packed sightseeing days, or a more relaxed "
                "mix with shopping, cafés and free time? And are there any must-do experiences — "
                "for example a Bosphorus cruise or the cable car?"))
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
                extra_queries = []
                if terms:
                    extra_queries.append(", ".join(terms))
                if intent == "revise" and state.itinerary:
                    previous = [activity["name"] for day in state.itinerary.get("days", [])
                                for activity in day.get("activities", []) if activity.get("name")]
                    if previous:
                        extra_queries.append(", ".join(previous))
                interests_query = normalize_interests(", ".join(
                    state.profile.interests or extracted.get("interests") or []))
                facts, research_calls = await research(mcp, destination, interests_query,
                    state.profile.start_date, state.profile.end_date, extra_queries=extra_queries)
                calls.extend(research_calls)
                agents.append({"name": "Researcher", "status": "completed"})
                attraction_result = facts.get("find_attractions", {})
                if attraction_result.get("error"):
                    if "not_cached" in attraction_result["error"]:
                        reply = (f"I don't have sourced travel data for {destination}: the travel data service "
                                 "is in replay mode and only covers Istanbul and Amman. Try one of those "
                                 "cities, or start the gateway with TRAVEL_MODE=live for other destinations.")
                    else:
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
                filled_dates = fill_empty_days(proposed, facts, profile, days, verified_costs, draft)
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
        web_citations = []
        web_note = ""
        activity_ask = bool(re.search(
            r"activit|adventure|experience|day trip|outside|something (fun|different)",
            req.message, re.I))
        if unsupported or facts.get("find_attractions", {}).get("interest_relaxed") \
                or (intent == "revise" and activity_ask):
            idea_query = ", ".join(dict.fromkeys(
                [*unsupported, *terms, *(extracted.get("interests") or [])])) \
                or req.message[:120]
            ideas = await web_activity_ideas(destination, idea_query)
            if ideas:
                lines = []
                for idea in ideas:
                    web_citations.append({"id": f"web-{len(web_citations) + 1}",
                                          "title": idea.get("title") or idea["url"],
                                          "url": idea["url"]})
                    snippet = (idea.get("snippet") or "").strip()
                    lines.append(f"- [{idea.get('title') or idea['url']}]({idea['url']})"
                                 + (f" — {snippet[:120]}" if snippet else ""))
                web_note = ("From live web search (unverified — outside the sourced plan, confirm "
                            "details yourself):\n" + "\n".join(lines))
        caveats = [auto_note] if auto_note else []
        if unsupported:
            caveats.append(f"The sourced listings for {destination} don't include {', '.join(unsupported)}, "
                           "so I couldn't schedule those from verified data — you'd need to arrange them "
                           "separately.")
        if filled_dates:
            caveats.append("I couldn't verify what was planned for "
                           + ", ".join(filled_dates)
                           + " in the sourced listings, so I filled that time with other "
                           "sourced places — tell me if you'd rather leave it free.")
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
        dropped_repeats = repeat_notes(draft, facts)
        if dropped_repeats:
            budget_note += " " + " ".join(dropped_repeats)
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
        reply = (f"Here's a sourced {plan_label} plan for {destination} — costs are estimates "
                 f"linked to their sources.{preference_note}{budget_note}"
                 + (" " + " ".join(caveats) if caveats else "")
                 + " Approve it to save the plan; nothing is booked or purchased. "
                 + "Want changes? Tell me things like \"add a Bosphorus cruise\", \"add the cable car\", "
                 + "\"more shopping, fewer museums\" or \"make day 1 cheaper\".\n\n"
                 + "\n".join(day_lines))
        if web_note:
            reply += "\n\n" + web_note
        sources = (collect_sources(facts) + web_citations +
                   [citation for cost in verified_costs.values()
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
        destination = state.profile.destination or extracted.get("destination")
        style_known = bool(state.profile.lodging_style) or state.profile.hotel_stars is not None
        board_known = bool(state.profile.hotel_board)
        if not destination or not (style_known and board_known):
            if not destination:
                reply = ("Which city are you staying in? Also tell me how many stars you want "
                         "(or budget / mid-range / luxury) and which meals — breakfast only, "
                         "half-board or all-inclusive.")
            else:
                needs = []
                if not style_known:
                    needs.append("how many stars (or budget / mid-range / luxury)")
                if not board_known:
                    needs.append("which meals — breakfast only, half-board or all-inclusive")
                reply = ("To search the web for hotels that fit you, tell me: " + " and ".join(needs)
                         + f". Optionally also a max price per night and a preferred area in {destination}.")
            agents[-1]["status"] = "completed"
            state.last_agents = agents
            state.history.append({"role": "assistant", "content": reply})
            save_session(state)
            return response(reply, state=state.model_dump(), usage=usage_summary())
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
        except Exception as exc:
            calls.append(tool_call("get_weather", False, "Weather Analyst"))
            err = str(exc)
            data = None
        if data is None:
            if "not_cached" in err:
                reply = (f"I don't have weather data for {city}: the travel data service is in replay "
                         "mode and only covers Istanbul and Amman.")
            else:
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

    if intent == "flight":
        agents.append({"name": "Flight Advisor", "status": "working"})
        origin = state.profile.origin or extracted.get("origin")
        needs = []
        if not origin:
            needs.append("which city you are flying from")
        if state.profile.flight_bags is None:
            needs.append("how many checked bags you want to take and roughly how many kg each")
        if not state.profile.flight_time_pref:
            needs.append("whether you prefer morning, afternoon or night flights — or it doesn't matter")
        if needs:
            reply = "To advise on flights and baggage, tell me: " + "; ".join(needs) + "?"
            agents[-1]["status"] = "completed"
            state.last_agents = agents
            state.history.append({"role": "assistant", "content": reply})
            save_session(state)
            return response(reply, state=state.model_dump(), usage=usage_summary())
        try:
            reply, usage, sources = await advise_flight(req.message, profile, state.history)
            record_usage(usage)
        except Exception:
            reply = ("I couldn't look up flight and baggage information right now. Please confirm exact "
                     "baggage rules and fares on the airline's website — I can't see live fares or book tickets.")
            sources = []
        agents[-1]["status"] = "completed"
        state.last_agents = agents
        state.last_sources = sources
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), citations=sources, usage=usage_summary())

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
        reply = GENERAL_FALLBACK
        agents.append({"name": "Coordinator", "status": "completed"})
    state.last_agents = agents
    state.history.append({"role": "assistant", "content": reply})
    save_session(state)
    return response(reply, state=state.model_dump(), usage=usage_summary())
