from __future__ import annotations

from .crew import CoordinatorOutput, CrewTaskSpec, run_crew
from ..core.models import TravelerProfile
from ..features.preference_intent import is_preference_save


async def coordinate(message: str, profile: TravelerProfile, history: list[dict]) -> tuple[dict, dict]:
    context = {"message": message, "profile": profile.model_dump(), "recent_history": history[-8:]}
    saving = is_preference_save(message)
    instructions = "Understand the request and return the JSON fields described."
    if saving:
        instructions = (
            "This is an explicit request to save personal travel preferences. Return intent remember. "
            "Extract the current message into preference_updates using only dietary, interests, budget_style, "
            "walking_tolerance, max_walk_minutes, home_currency, travel_party, notes. "
            "For example, 'Remember that I am vegetarian and enjoy museums and history' means "
            "preference_updates: {dietary: [vegetarian], interests: [museums, history]}. "
            "Do not recommend places or search the web. Do not claim anything was saved. "
            "Use question null; the application will request approval before saving."
        )
    result, usage, _ = await run_crew(
        [CrewTaskSpec(
            "coordinator",
            instructions,
            CoordinatorOutput,
        )],
        context,
    )
    if saving:
        result["intent"] = "remember"
    return result, usage
