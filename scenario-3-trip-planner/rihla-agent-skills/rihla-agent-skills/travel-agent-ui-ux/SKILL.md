---
name: travel-agent-ui-ux
description: Use when designing or improving Rihla's traveller-facing chat, itinerary display, maps, comparison views, approval flow, responsive layout, accessibility, or error states.
---

# Rihla travel product UI/UX

## Goal
Make Rihla understandable and trustworthy to a non-technical traveller. Prioritize clarity of the trip and its decisions over decorative chat UI.

## Core screens and states
- Trip request and missing-information clarification.
- Proposed itinerary, grouped by day.
- Map and route context where coordinates/routes are available.
- Activity cards with time, duration, estimated cost, source, and opening-hours status.
- Warnings for stale, conflicting, or unknown information.
- Original vs revised itinerary comparison.
- Pending action with clear approve/reject controls.
- Saved trip confirmation using the actual returned trip ID.
- Loading, empty, partial-data, timeout, and failure states.

## UX rules
- Keep the itinerary as a first-class structured view; chat is the control surface, not the only place information appears.
- Show why an activity was recommended and what evidence supports it.
- Label estimates and unknowns visibly.
- Distinguish proposed, approved, and saved states.
- Before approval, summarize exactly what will be saved.
- Make revisions understandable with a change summary rather than silently replacing the plan.
- Do not display fake booking buttons, live availability, ratings, prices, or maps data.
- Support keyboard navigation, readable contrast, responsive layouts, and accessible labels.
- Avoid overwhelming the user with every internal agent thought or raw tool trace. Expose useful decisions, evidence, and concise execution details.

## Implementation
Inspect the existing UI framework and component conventions first. Reuse the design system and avoid adding dependencies unless necessary. Keep API calls and state transitions explicit.

## Tests
Check mobile/desktop layouts, long itineraries, missing images/coordinates, stale data, approval/rejection, partial failures, keyboard use, and accessible control labels.
