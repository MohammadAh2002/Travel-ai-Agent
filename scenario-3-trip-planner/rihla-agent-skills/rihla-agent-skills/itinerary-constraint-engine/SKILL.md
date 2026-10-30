---
name: itinerary-constraint-engine
description: Use when implementing itinerary scheduling, route ordering, budget calculations, walking limits, opening-hour checks, date validation, or other deterministic trip constraints.
---

# Itinerary constraint engine

## Goal
Implement hard travel constraints in deterministic, testable code rather than relying on an LLM prompt to obey them.

## Separate constraints
Hard constraints (must pass or be explicitly unresolved):
- Trip dates are valid and activities occur within the trip.
- No overlapping activity time slots.
- Opening hours must be compatible with the planned visit when known.
- Required budget limits must be respected, or the plan must clearly report that it cannot satisfy them.
- Walking/travel limits must be respected when the necessary route data exists.
- Required traveller and activity fields must satisfy the API schema.

Soft preferences (optimize, but explain trade-offs):
- Interest match.
- Preferred pace.
- Fewer transfers or shorter routes.
- Variety of activities.
- Preferred meal times and neighbourhoods.

## Implementation approach
1. Inspect existing itinerary schemas and computed Trip Store fields.
2. Normalize dates, time zones, currencies, and durations explicitly.
3. Use route tools for supported place pairs; never estimate a missing route silently.
4. Treat unknown opening hours as unknown, not as open.
5. Keep price calculations separate from presentation. Track currency and conversion-rate date/method.
6. Return structured validation results: `valid`, `errors`, `warnings`, `unverified`, and `metrics`.
7. Make each rule independently testable.
8. If constraints conflict, explain the conflict and ask which soft preference may be relaxed. Do not quietly violate a hard constraint.

## Useful metrics
Total estimated cost, cost by day, total activities, activity overlaps, route duration, walking duration, unverified hours, and constraint violations.

## Tests
Cover boundaries, timezone/date edges, closed days, unknown hours, missing routes, currency conversion, budget overrun, overlapping activities, and impossible combinations.
