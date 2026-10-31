from __future__ import annotations

from .crew import CrewTaskSpec, SpecialistOutput, run_crew


async def advise_documents(question: str, nationality: str | None, destination: str | None,
                           sources: list[dict]) -> tuple[str, dict]:
    data, usage, roles = await run_crew(
        [CrewTaskSpec(
            "documents_advisor",
            "Answer the document question using only supplied government references.",
            SpecialistOutput,
        )],
        {"question": question, "passport_nationality": nationality,
         "destination": destination, "official_references": sources},
    )
    usage["agents_run"] = roles
    return data["answer"], usage
