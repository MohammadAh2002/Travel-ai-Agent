from __future__ import annotations

from ..features.web_search import web_search
from .crew import CrewTaskSpec, SpecialistOutput, run_crew


async def answer_general(question: str, history: list[dict] | None = None) -> tuple[str, dict, list[dict]]:
    """Answer an out-of-scope or general question: live web search first, own knowledge as backup."""
    search = await web_search(question)
    results = search["results"]
    data, usage, roles = await run_crew(
        [CrewTaskSpec(
            "general_agent",
            "Answer the question helpfully and directly. Use the supplied live web-search "
            "results where they are relevant and cite them as markdown links, and fill in the "
            "rest from your own knowledge. Keep it conversational and concise."
            if results else
            "Web search returned nothing for this question, so answer from your own "
            "knowledge. Add one short note that it could not be checked online just now. "
            "Never refuse to answer.",
            SpecialistOutput,
        )],
        {"question": question, "web_results": results,
         "recent_history": (history or [])[-6:]},
    )
    usage["agents_run"] = roles
    citations = [{"id": f"web-{index + 1}", "title": item.get("title") or item["url"],
                  "url": item["url"]}
                 for index, item in enumerate(results) if item.get("url")]
    return data["answer"], usage, citations
