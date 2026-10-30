---
name: travel-agent-ui-design
description: Use when designing, implementing, or improving the Rihla travel-agent frontend, including visual direction, layout, itinerary views, maps, chat, responsive behavior, accessibility, and interaction states. Prioritize a polished, distinctive travel product rather than a generic AI-chat interface.
---

# Rihla UI design and frontend implementation

## Mission

Build a polished, modern travel-planning product that makes planning and managing a trip feel clear, visual, trustworthy, and enjoyable.

Rihla should feel like a capable travel companion and trip workspace, not a generic chatbot skin. The itinerary is the main product surface; chat is an important way to control and revise it, but should not be the only way users understand their trip.

## 1. Inspect before changing

Before implementation:

1. Inspect the repository structure, frontend framework, package versions, routing, styling system, existing components, assets, and current screens.
2. Run the app and inspect the actual UI at desktop and mobile sizes if the environment permits.
3. Read the API schemas and sample responses before designing data-dependent components.
4. Identify existing design conventions and reuse them where they are good.
5. Do not assume endpoints, fields, map providers, image URLs, or functionality. Verify them in the code.
6. Make a concise UI improvement plan before large changes.

Do not replace the existing frontend stack or add a large UI dependency without a clear reason.

## 2. Product experience principles

- Make the trip, itinerary, and decisions the visual focus.
- Use a clear information hierarchy: destination and dates, trip summary, day-by-day itinerary, map, budget, and supporting details.
- Keep the interface calm and uncluttered. Avoid excessive gradients, glass effects, decorative cards, emoji, and unnecessary animation.
- Use consistent spacing, typography, colors, radii, shadows, and iconography.
- Use real travel imagery only when available and properly sourced. Do not invent images, ratings, prices, reviews, or booking availability.
- Make the interface feel cohesive across the landing/request flow, planning state, itinerary, revision flow, and saved-trip state.
- Prefer useful visual structure over long blocks of chat text.
- Avoid presenting internal chain-of-thought or private agent reasoning. Show concise explanations, evidence, decisions, and actionable findings instead.

## 3. Core screens and components

Design and implement only what the existing product/API supports.

### Trip creation
- Clear destination, dates, traveller count, budget, currency, interests, pace, and mobility preferences.
- Ask for essential missing information progressively rather than showing an intimidating form.
- Provide helpful examples and validation.
- Make the primary action obvious.

### Planning experience
- Show a clear planning state with meaningful stages, such as researching, building the schedule, and checking constraints.
- Do not fake progress percentages or claim an agent completed work when it has not.
- Handle slow requests, cancellation if supported, and failures gracefully.

### Itinerary workspace
- Organize activities by day and time.
- Show place name, short description, estimated duration, estimated cost, and relevant travel time when supplied.
- Show opening-hours status as verified, unknown, or conflicting based on actual data.
- Display source attribution and freshness near the relevant facts.
- Include a map only when usable coordinates or supported map data exist.
- Make the itinerary easy to scan and edit.

### Revision and comparison
- Clearly distinguish the original plan, proposed revision, approved revision, and saved trip.
- Show a concise change summary: added, removed, moved, or modified activities.
- Show updated budget, walking time, and other affected metrics.
- Never silently replace a saved itinerary with an unapproved proposal.

### Approval and persistence
- Before approval, summarize exactly what will be saved.
- Provide clear approve and reject actions.
- Show success only after the API confirms the save.
- Display the actual returned trip identifier if the product uses one.
- Prevent accidental repeated actions in the UI while a request is pending, while still relying on backend idempotency/security for correctness.

### Empty, loading, and error states
Design intentional states for:
- No trip yet.
- No activities found.
- Missing coordinates or images.
- Unknown opening hours or prices.
- Partial research results.
- API/MCP timeout or failure.
- Validation issues.
- Pending approval.
- Save rejected or failed.

Explain what happened and offer a useful next action. Do not hide errors behind generic "Something went wrong" messages.

## 4. Visual design direction

Use a distinctive, editorial travel aesthetic:

- A warm, light neutral base with a restrained accent palette, unless the existing brand direction says otherwise.
- Strong, readable typography and generous whitespace.
- Large destination imagery where it adds value.
- Clear day sections and activity timelines.
- Compact metadata for duration, cost, walking, and opening hours.
- Consistent icon style; use the project's installed icon library if present.
- Subtle transitions only when they improve orientation or feedback.

Avoid copying another travel platform's exact layout or branding. Use competitor research as inspiration, not as a template to reproduce.

## 5. Responsive behavior

Support small mobile screens, tablet, and desktop.

- On mobile, prioritize the current day and make day navigation easy.
- Keep key actions reachable without horizontal scrolling.
- Convert side-by-side panels into a sensible stacked layout.
- Make maps usable without consuming the entire screen.
- Ensure long place names, translated text, and large itineraries do not break layouts.
- Test narrow widths, not just a single desktop viewport.

## 6. Accessibility and internationalization

- Use semantic HTML and accessible names for controls.
- Support keyboard navigation and visible focus.
- Maintain readable contrast and comfortable text sizes.
- Do not communicate status by color alone.
- Respect the project's supported languages and RTL behavior if present.
- Avoid hardcoded layout assumptions that break with longer translations.
- Format dates, times, and currencies using locale-aware utilities already in the project.

## 7. Frontend engineering rules

- Follow the existing framework and component conventions.
- Keep reusable components focused and typed according to the project's patterns.
- Separate API/data logic from presentation.
- Handle loading, error, empty, and success states explicitly.
- Avoid duplicating business rules already enforced by the backend.
- Do not trust the UI as the security boundary; backend validation and approval checks remain authoritative.
- Avoid unnecessary global state and dependencies.
- Preserve API contracts and existing working behavior.
- Do not use fake/mock values in production UI unless clearly labelled as demo data.

## 8. Interaction quality

Every visible control must work.

- Buttons need real actions and clear disabled/loading states.
- Forms need validation and useful error messages.
- Tabs, filters, sorting, day navigation, and dialogs must behave consistently.
- Confirm destructive or irreversible actions.
- Preserve user input when recoverable errors occur.
- Use optimistic updates only when rollback and consistency behavior are implemented.
- Do not add decorative controls that look functional but do nothing.

## 9. UI verification checklist

After changes:

1. Run the project using its documented command.
2. Run lint, type-check, and relevant frontend tests where available.
3. Verify the primary trip creation -> itinerary -> revision -> approval/save journey.
4. Test loading, empty, partial-data, API failure, and validation states.
5. Check desktop and mobile layouts.
6. Check keyboard navigation, focus, and accessible labels.
7. Verify all displayed values come from real API data or are clearly marked as estimates.
8. Confirm no existing API contract or approval behavior was bypassed.

If browser-based visual inspection is unavailable, say so and report which checks were actually run.

## 10. Definition of done

A UI task is complete only when:

- The screen is visually consistent with the rest of Rihla.
- It works at mobile and desktop sizes.
- Every visible control performs its intended action.
- Loading, empty, and error states are handled.
- Data provenance and uncertainty are not hidden.
- Existing trip, MCP, API, and approval flows still work.
- Relevant tests and checks have been run and their exact results reported.

## Final report

Summarize:
- Screens/components changed.
- Main UX decisions.
- Responsive and accessibility work.
- Tests and checks actually run.
- Known limitations or manual verification still required.
