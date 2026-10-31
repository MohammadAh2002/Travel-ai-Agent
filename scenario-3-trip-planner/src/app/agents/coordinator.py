from __future__ import annotations

from .crew import CoordinatorOutput, CrewTaskSpec, run_crew
from ..core.models import TravelerProfile


async def coordinate(message: str, profile: TravelerProfile, history: list[dict]) -> tuple[dict, dict]:
    context = {"message": message, "profile": profile.model_dump(), "recent_history": history[-8:]}
    result, usage, _ = await run_crew(
        [CrewTaskSpec(
            "coordinator",
            "Understand the request and return the JSON fields described.",
            CoordinatorOutput,
        )],
        context,
    )
    return result, usage
