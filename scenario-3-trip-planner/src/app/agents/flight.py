from __future__ import annotations

from .crew import CrewTaskSpec, SpecialistOutput, run_crew
from .lodging import _gather_results


async def advise_flight(message: str, profile: dict | None = None,
                        history: list[dict] | None = None) -> tuple[str, dict, list[dict]]:
    """Flight and baggage guidance using live web-search evidence plus advisor knowledge."""
    profile = profile or {}
    origin = (profile.get("origin") or "").strip()
    destination = (profile.get("destination") or "").strip()
    route = " to ".join(part for part in (origin, destination) if part)
    results, _error = await _gather_results([
        f"baggage allowance flights {route}".strip(),
        f"checked bag kg fee airlines {route}".strip(),
        f"best time to book flights {route}".strip(),
    ])
    data, usage, roles = await run_crew(
        [CrewTaskSpec(
            "flight_advisor",
            "Give practical flight and baggage guidance for this traveller. Use exactly the party, "
            "bag count/weight and time preference stated in the context. Work from the supplied "
            "web-search results first and link sources; use general knowledge for common carrier "
            "rules when results are thin. Cover: typical checked/cabin baggage allowances on this "
            "kind of route and how the traveller's stated bags and weights compare; cost "
            "differences between carry-on-only and checked-bag fares where evidence exists; and one "
            "line matching their morning/night preference (or 'no preference' if that is what they "
            "said) to practical advice for their party. Never invent specific fares, schedules or "
            "airline names that are not in evidence or common knowledge, and never claim you cannot "
            "search the web. Close with one short note that fares and rules must be confirmed on "
            "the airline site. Under ~130 words, no preamble."
            + (" Web search returned no usable results, so rely on general knowledge only."
               if not results else ""),
            SpecialistOutput,
        )],
        {"message": message, "profile": profile, "web_results": results,
         "recent_history": (history or [])[-6:]},
    )
    usage["agents_run"] = roles
    citations = [{"id": f"web-{index + 1}", "title": item.get("title") or item["url"],
                  "url": item["url"]}
                 for index, item in enumerate(results) if item.get("url")]
    return data["answer"], usage, citations
