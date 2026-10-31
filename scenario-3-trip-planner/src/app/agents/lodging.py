from __future__ import annotations

from ..features.web_search import web_search
from .crew import CrewTaskSpec, SpecialistOutput, run_crew


async def advise_lodging(message: str, profile: dict | None = None,
                         history: list[dict] | None = None) -> tuple[str, dict, list[dict]]:
    """Suggest accommodation options using live web-search evidence."""
    profile = profile or {}
    destination = (profile.get("destination") or "").strip()
    query = " ".join(part for part in [destination, "hotel", message] if part).strip()
    search = await web_search(query)
    if not search["results"] and destination:
        search = await web_search(f"hotels in {destination}")
    if not search["results"]:
        detail = f" ({search['error']})" if search.get("error") else ""
        return (f"I couldn't retrieve live hotel listings right now{detail}. "
                "If you share your hotel name or area, I can still help assess how it "
                "may affect your itinerary."), {"cost_usd": None}, []
    data, usage, roles = await run_crew(
        [CrewTaskSpec(
            "lodging_advisor",
            "Suggest hotels matching the traveller's stated constraints using only the supplied "
            "live web-search results. Present up to three options as name — what the source "
            "supports — markdown link. Make clear these are unverified web suggestions: you "
            "cannot check real-time rates or availability, and the traveller should confirm "
            "star rating, walking distance to transit, and current prices on a booking site. "
            "Add one line on how the area affects their day plan. If the results are too thin "
            "to name hotels, say so and explain which detail (dates, budget range, "
            "neighbourhood) would narrow the search.",
            SpecialistOutput,
        )],
        {"message": message, "profile": profile, "web_results": search["results"],
         "recent_history": (history or [])[-6:]},
    )
    usage["agents_run"] = roles
    citations = [{"id": f"web-{index + 1}", "title": item.get("title") or item["url"],
                  "url": item["url"]}
                 for index, item in enumerate(search["results"]) if item.get("url")]
    return data["answer"], usage, citations
