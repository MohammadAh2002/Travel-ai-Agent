---
name: adaptive-trip-replanning
description: Use when implementing user-requested itinerary changes or recovery from changed weather, closures, budget, mobility, preferences, or unavailable data while preserving unaffected parts of a saved or proposed trip.
---

# Adaptive trip replanning

## Goal
Revise the smallest affected part of a trip while preserving the traveller's intent and all unaffected activities.

## Workflow
1. Load the current itinerary and relevant traveller preferences.
2. Identify the change: new constraint, user edit, weather change, closure, route disruption, or source failure.
3. Determine exactly which days and activities are affected.
4. Re-research only what is necessary using available MCP tools.
5. Generate one or more supported replacements.
6. Recalculate dates, opening hours, routes, walking time, budget, and citations for affected days and the whole trip.
7. Run the deterministic constraint engine and critic.
8. Present a diff: kept, moved, removed, added, changed, and unresolved.
9. Ask for approval before saving any change.

## Preservation rules
- Do not discard unaffected activities.
- Do not change dates or traveller count unless requested or required and approved.
- Do not exceed the budget or walking limit silently.
- Do not claim live disruption information if the available source does not provide it.
- If the data source is unavailable, explain the limitation and offer only alternatives supported by available data.
- Keep the original proposal intact until the revised proposal is accepted.

## Output
Return the revised itinerary plus a human-readable change summary and recalculated metrics.

## Tests
Test a 20% budget reduction, a rainy day, a known museum closure, a reduced walking limit, one unavailable data source, and a request that affects only one activity.
