---
name: travel-data-provenance
description: Use when researching travel facts, displaying recommendations, handling source citations, prices, opening hours, weather, exchange rates, stale cache results, or conflicting information in Rihla.
---

# Travel data provenance and uncertainty

## Goal
Every factual travel claim must be traceable to returned data. Clearly distinguish verified fields, estimates, unknowns, stale values, and conflicting sources.

## Rules
- Use only facts returned by the project's tools or explicitly supplied by the traveller.
- Preserve each result's `source`, `source_url`, `licence`, `retrieved_at`, `mode`, and citation object when available.
- Attach citations to the claims they support. Do not cite a source for facts it does not contain.
- Do not invent prices, opening hours, coordinates, availability, travel times, ratings, or booking options.
- If opening hours are absent or ambiguous, report them as unknown and do not assert that a place is open.
- Present prices as estimates when the source indicates they may be old. Preserve `as_of_year` or equivalent freshness metadata.
- If sources conflict, show the conflict or a range and identify the sources. Do not silently choose the more convenient value.
- Distinguish replay data from live data. If a cached result is stale, disclose that status.
- Do not imply that dietary mentions certify a restaurant as safe for an allergy or dietary requirement.
- Respect source licences and required attribution, including Wikivoyage CC BY-SA, OpenStreetMap ODbL, Open-Meteo CC BY, and ECB attribution as applicable.

## Suggested evidence model
For each recommendation, retain:
- claim / field
- value
- source title and URL
- retrieved timestamp
- data mode
- freshness status
- uncertainty reason (if any)

Do not invent a numerical confidence score unless a documented, testable scoring method exists.

## Tests
Test missing provenance, stale prices, conflicting prices, unknown hours, stale replay results, and citations surviving through the final chat response and saved itinerary.
