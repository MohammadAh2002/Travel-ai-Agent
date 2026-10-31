from __future__ import annotations

from .crew import CriticOutput, CrewTaskSpec, run_crew


async def verify_itinerary(itinerary: dict, facts: dict,
                           specialist_findings: list[dict] | None = None) -> tuple[dict, dict]:
    result, usage, roles = await run_crew(
        [CrewTaskSpec(
            "itinerary_critic",
            "Verify this draft strictly against the tool results and deterministic checks.",
            CriticOutput,
        )],
        {"itinerary": itinerary, "research": facts, "specialist_findings": specialist_findings or []},
    )
    usage["agents_run"] = roles
    return result, usage
