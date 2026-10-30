from __future__ import annotations

from ..llm import complete
from ..models import TravelerProfile

SYSTEM = """You are Rihla's travel-intake coordinator. Return JSON only. Extract trip needs from the conversation
and the existing profile. Respect all prior conversation state. Never invent dates, budget, party size, or ages.
Ask one concise clarifying question when essential facts are missing or ambiguous. For a trip itinerary, essential
facts are destination, dates or number of days, total budget/currency, party size (including children's ages when
children are present), and trip style (walking/hiking/relaxed). Ask about lodging style only when it changes the
day plan, and ask the traveller if they will use a hotel as a base or spend meaningful time there. A lone traveller
or explicitly adult-only party may be treated as adults, but say the assumption. For flight packing questions,
ask whether they expect to buy many gifts if it affects baggage advice. If the user clearly asks about documents,
nearby places, checklist, or a general travel question, route to that intent without demanding itinerary fields.
Return {intent, destination, target_place, start_date, end_date, days, adults, children_count, children_ages, budget, currency, interests,
lodging_style, walking_style, origin, gift_heavy, passport_nationality, minutes, preference_updates, question,
assumption}. intent is one of itinerary, day_plan, documents, nearby, checklist, general, revise, price, watch,
remember. For remember, preference_updates may use only dietary, interests, budget_style, walking_tolerance,
max_walk_minutes, home_currency, travel_party, or notes. Include minutes when a nearby time radius is specified.
Use null for unknowns, arrays for lists."""


async def coordinate(message: str, profile: TravelerProfile, history: list[dict]) -> tuple[dict, dict]:
    context = {"message": message, "profile": profile.model_dump(), "recent_history": history[-8:]}
    return await complete(SYSTEM, "Understand the request and return the JSON fields described.", context)
