from __future__ import annotations

from ..features.web_search import web_search
from .crew import CrewTaskSpec, SpecialistOutput, run_crew


async def answer_general(question: str, history: list[dict] | None = None) -> tuple[str, dict, list[dict]]:
    """Answer an out-of-scope or general question using live web-search evidence."""
    search = await web_search(question)
    if not search["results"]:
        detail = f" ({search['error']})" if search.get("error") else ""
        return (f"I couldn't retrieve live web results for that{detail}. "
                "Please rephrase or try again in a moment."), {"cost_usd": None}, []
    data, usage, roles = await run_crew(
        [CrewTaskSpec(
            "general_agent",
            "Answer the question using only the supplied live web-search results. "
            "Cite the sources used as markdown links.",
            SpecialistOutput,
        )],
        {"question": question, "web_results": search["results"],
         "recent_history": (history or [])[-6:]},
    )
    usage["agents_run"] = roles
    citations = [{"id": f"web-{index + 1}", "title": item.get("title") or item["url"],
                  "url": item["url"]}
                 for index, item in enumerate(search["results"]) if item.get("url")]
    return data["answer"], usage, citations
