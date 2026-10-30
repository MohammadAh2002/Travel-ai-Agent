from __future__ import annotations

from ..llm import complete

SYSTEM = """You are a travel-document information advisor. Answer only from official government sources supplied in
the context. The right answer depends on passport nationality, destination, transit countries and dates; ask
focused questions if missing. Never determine legal eligibility. If a relevant official source is not supplied,
say you cannot verify it and advise the traveller to contact the destination country's embassy/consulate by phone
or email before travel. Cite exact official URLs from context only. Be clear that rules can change."""


async def advise_documents(question: str, nationality: str | None, destination: str | None,
                           sources: list[dict]) -> tuple[str, dict]:
    data, usage = await complete(SYSTEM, "Answer the document question using only supplied government references.",
                                 {"question": question, "passport_nationality": nationality,
                                  "destination": destination, "official_references": sources}, json_mode=False)
    return str(data), usage
