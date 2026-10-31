from __future__ import annotations

from .crew import (
    CrewTaskSpec,
    ItineraryOutput,
    PlaceResearchOutput,
    SpecialistOutput,
    run_crew,
)


async def draft_itinerary(profile: dict, facts: dict, days: int,
                          intent: str = "itinerary") -> tuple[dict, dict]:
    context = {"profile": profile, "research": facts, "days": days}
    tasks = [
        CrewTaskSpec(
            "place_researcher",
            f"Review the MCP evidence and the traveller's current request. Return exact candidate place names from the evidence — explicitly requested places first, then other sourced places that suit the traveller — enough distinct candidates to fill {days} day(s), plus concise source, closure, or price caveats.",
            PlaceResearchOutput,
        ),
        CrewTaskSpec(
            "budget_analyst",
            "Review the listed price evidence and traveller budget. Report price conflicts, unknown costs, and caveats only. Do not calculate totals; Python will do that.",
            SpecialistOutput,
        ),
    ]
    if profile.get("lodging_style"):
        tasks.append(CrewTaskSpec(
            "lodging_advisor",
            "Explain how the traveller's supplied lodging style affects the daily plan. Do not recommend or invent hotels or hotel prices.",
            SpecialistOutput,
        ))
    revision = intent == "revise" and bool(profile.get("current_itinerary"))
    instructions = (
        f"Use the traveller's current message to revise the existing itinerary, preserving unaffected days and applying the requested constraints. "
        f"Return a complete {days}-day itinerary with YYYY-MM-DD dates and local time HH:MM."
        if revision else
        f"Draft a {days}-day itinerary with YYYY-MM-DD dates and local time HH:MM."
    )
    tasks.append(CrewTaskSpec(
        "revision_specialist" if revision else "itinerary_planner",
        instructions,
        ItineraryOutput,
    ))
    result, usage, roles = await run_crew(tasks, context)
    usage["agents_run"] = roles
    return result, usage
