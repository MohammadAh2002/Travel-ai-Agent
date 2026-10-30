---
name: itinerary-critic-agent
description: Use when implementing or improving an independent review step that checks a proposed Rihla itinerary for feasibility, data quality, preference fit, and evidence before it is shown or saved.
---

# Itinerary critic agent

## Goal
Review a proposed itinerary independently and produce actionable, evidence-backed findings. The critic must not merely approve another agent's work.

## Review checklist
- Dates and weekdays match the intended trip.
- Opening hours support the scheduled visit; unknown hours are flagged.
- Activities do not overlap.
- Consecutive stops have supported route data and plausible travel time.
- Budget totals are calculated from activity costs and use one declared currency.
- Meal choices respect stated preferences as far as source data supports; allergy safety is never inferred from keyword mentions.
- Walking pace and activity density fit the traveller's stated preferences.
- Every factual claim has provenance.
- Stale, conflicting, synthetic, or missing data is flagged.
- No unsupported hotel, flight, availability, or booking claim is introduced.

## Output format
Return structured findings with:
- `severity`: critical / warning / info
- `category`
- `activity_or_day`
- `description`
- `evidence`: source/tool result references
- `suggested_fix`
- `requires_user_decision`

The critic should distinguish a genuine violation from an unknown that needs disclosure. It should not invent a fix when no supported alternative exists.

## Revision loop
Allow a bounded number of planner -> critic -> revision cycles. Stop when hard checks pass, no meaningful fix is available, or the iteration limit is reached. Return unresolved issues honestly.

## Tests
Include known closure, schedule overlap, stale price, missing route, dietary ambiguity, unsupported claim, and a valid itinerary that should pass without unnecessary edits.
