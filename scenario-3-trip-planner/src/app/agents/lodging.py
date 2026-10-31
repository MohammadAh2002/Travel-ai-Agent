from __future__ import annotations

import asyncio

from ..features.web_search import web_search
from .crew import CrewTaskSpec, SpecialistOutput, run_crew


async def _gather_results(queries: list[str]) -> tuple[list[dict], str | None]:
    """Run the web searches concurrently, merge and de-duplicate results by URL."""
    searches = await asyncio.gather(*(web_search(query) for query in queries if query))
    results, seen, error = [], set(), None
    for search in searches:
        error = error or search.get("error")
        for item in search["results"]:
            url = item.get("url")
            if url and url not in seen:
                seen.add(url)
                results.append(item)
    return results, (error if not results else None)


async def advise_lodging(message: str, profile: dict | None = None,
                         history: list[dict] | None = None) -> tuple[str, dict, list[dict]]:
    """Suggest accommodation options using live web-search evidence plus advisor knowledge."""
    profile = profile or {}
    destination = (profile.get("destination") or "").strip()
    style = " ".join(part for part in [
        f"{profile['hotel_stars']}-star" if profile.get("hotel_stars") else
        (profile.get("lodging_style") or "").strip(),
        (profile.get("hotel_board") or "").strip(),
        (profile.get("hotel_area") or "").strip(),
        f"under {int(profile['hotel_budget'])} per night" if profile.get("hotel_budget") else "",
    ] if part).strip()
    primary = " ".join(part for part in [destination, "hotel", style, message] if part).strip()
    results, _error = await _gather_results([
        primary,
        f"best {style} hotels {destination}".strip() if destination else "",
    ])
    if len(results) < 3 and destination:
        more, _ = await _gather_results([f"hotels in {destination} prices reviews"])
        known = {item.get("url") for item in results}
        results += [item for item in more if item.get("url") not in known]
    data, usage, roles = await run_crew(
        [CrewTaskSpec(
            "lodging_advisor",
            "Recommend up to three hotels that fit the traveller's stated preferences "
            "(star rating, meals/board, budget per night, area, distance to transit). Prefer "
            "hotels named in the supplied web results and link each to its source; if the "
            "results name few or no hotels, still suggest well-known options in that area "
            "from your own knowledge — never mention that search returned nothing and never "
            "say you cannot search the web. Compare options briefly on price, rating or "
            "location where evidence exists — never invent rates or amenities. Format each "
            "option as '**Name** — one line on why it fits — link'. Close with a single "
            "short note that suggestions are unverified and should be confirmed on a booking "
            "site. If one missing detail would sharpen the picks (dates, exact area), ask it "
            "as one short final question. Under ~120 words, no preamble."
            + (" Web search returned no usable results, so rely on your knowledge only."
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
