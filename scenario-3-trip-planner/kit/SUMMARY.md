# Rihla — build summary and presentation notes

Rihla is a conversational trip-planning crew that researches sourced activities, asks for missing trip details, drafts a revisable itinerary and saves it only after explicit approval.

## What was built

- **A six-role agent workflow:** Coordinator, Researcher, Budget Analyst, Itinerary Planner, Verifier and Documents Advisor. The LLM coordinates and drafts; code handles API calls, date checks, price conversions, state, and approval.
- **A modern browser UI:** responsive chat-first interface, quick-start suggestion chips, microphone recording, inline itinerary cards with sources, Leaflet stop map and approve/reject controls. Trip details (dates, budget, party size) are collected conversationally — there is no separate form.
- **MCP travel research:** reads destinations, attractions, restaurant listings, hours, weather, coordinates, routes, currency and saved preferences from the provided MCP server.
- **Trip memory:** session state carries the conversation. Saved traveller preferences are read from the Trip Store; new persistent preferences require the same explicit approval step before they are saved.
- **Trust controls:** no model-accessible write tools; exact pending action and idempotency key at approval; source URLs must match returned listing data; untrusted descriptions are data, not instructions; synthetic attraction listings are excluded.
- **Additional travel help:** official-government document source directory, map-link/coordinate nearby search, day planning, a pre-travel checklist, baggage/seat-selection reminders for gift-heavy trips, and hourly weather/currency watches.
- **Shipping and evaluation:** FastAPI app, Dockerfile/Compose, API health endpoint, extra evaluation cases, architecture diagram, and this presentation guide.

## Every feature and how to use it

Everything happens in the chat at `http://localhost:8000` — just type (or speak) in plain words. The AI asks a follow-up question whenever an essential detail is missing; there are no forms.

### Planning

1. **Multi-day trip itinerary** — Builds a sourced day-by-day plan (up to 14 days) with times, walking minutes between stops, converted cost estimates and a route map. The AI asks for whatever is missing: destination, dates or number of days, total budget and currency, party size, children's ages, pace (walking / hiking / relaxed), interests, and whether the hotel is just for sleeping or part of the experience.
   - *Use:* "Plan a 4-day trip to Istanbul from 12 May for 2 adults and a 7-year-old, budget 900 USD, we love history and food, relaxed pace."
   - *Use:* "Plan a trip." — the AI will ask for the details one by one.
2. **Itinerary revision** — Change a proposed or saved plan conversationally. The revision keeps the current itinerary as context and produces a new proposal that again needs your approval; nothing is silently replaced.
   - *Use:* "Make day 2 more relaxed" · "Swap the museum for something outdoors" · "Move the bazaar to the last day."
3. **One-day plan** — Designs a single great day, asking where, which date, who is coming (including ages), walking style, budget and hotel use.
   - *Use:* "Plan one great day in Amman on 3 June for two adults, we like walking."
4. **Approve / reject (the hard gate)** — Every proposed plan shows an inline itinerary card with **Approve & save** / **Not now**. Only after you approve does code (never the LLM) save the exact approved payload to the simulated Trip Store, using the action ID as the idempotency key — repeated approvals can't duplicate a save. You get back the real `TRIP-…` ID.
   - *Use:* review the card in chat, click a button — or say "approve" is not enough; the button is the gate.

### Questions and lookups

5. **Price check** — Shows the listed price for a specific place in the current destination, flags disagreement between sources instead of presenting one number as certain, and labels it an estimate, never a live quote.
   - *Use:* "How much is the Hagia Sophia ticket?" (after mentioning Istanbul)
6. **Nearby places** — Finds food, sights and more around a Google Maps link, pin or raw coordinates, within a walking radius you choose. Distances are straight-line walking-time estimates.
   - *Use:* "What's good to eat within 15 minutes of 41.0082, 28.9784?" or paste a Maps link.
7. **Travel documents advisor** — Answers visa/entry questions using official government sources only. It asks for your passport nationality, destination, transit countries and dates when needed. Informational, not legal advice.
   - *Use:* "What documents do I need to enter Jordan with a German passport?"
8. **Pre-travel checklist** — A practical preparation list tailored to your destination (local transit/ride apps), your party (child tickets and breaks), your itinerary (print tickets, verify opening hours) and gift-heavy trips (baggage allowance advice).
   - *Use:* "My trip is booked — what should I prepare?"
9. **General travel Q&A** — Routes any other travel question to a concise answer without demanding itinerary fields.

### Memory and monitoring

10. **Preference memory** — Remembers lasting preferences (diet, interests, budget style, walking limits, home currency, travel party). Saving preferences goes through the same explicit approval step; saved preferences are then applied automatically on future chats for a known traveller.
    - *Use:* "Remember that I'm vegetarian and prefer a slow pace."
11. **Hourly trip watch** — A background watcher re-checks weather for your dates and your budget currency every hour (max 10 watches per session). Honest scope: weather and FX only — no hotel or flight price feeds exist.
    - *Use:* "Watch my Istanbul trip for weather and currency changes." · Stop one with `DELETE /api/watch/{watch_id}`.
12. **Session memory** — The conversation carries context within a session, so follow-ups like "and what about the kids?" work without repeating everything. State is in-process and clears on restart.

### Input and safety

13. **Voice input** — Click the microphone in the composer, speak, click again to send. A local faster-whisper model transcribes; the transcript enters the chat like typed text. Text chat works fine without the optional voice dependency.
14. **Guardrails** — Messages over 5,000 characters and prompt-injection attempts ("ignore previous instructions…") are deflected. Replies can't claim anything was booked or purchased, and links not returned by the travel tools are stripped.
15. **Evidence and honesty** — Only places returned by the travel tools may appear in a plan; synthetic test listings are excluded; source URLs come from tool results, not the model. Closed weekdays are removed or moved with a note; unknown prices stay unknown and out of totals; adult ticket prices are multiplied and labelled as such.

### Six roles behind the chat

Coordinator (reads intent, asks follow-ups) → Researcher (MCP listings, hours, weather) → Budget Analyst (currency conversion, party costs) → Itinerary Planner (draft days) → Verifier (approves or blocks the proposal) → Documents Advisor (official sources). The "Crew" and "Research trail" lines under replies show which roles and tools actually ran.

### Example session

1. "Plan a trip" → AI asks destination, dates, budget, party.
2. "Istanbul, 12–15 May, 2 adults + 7-year-old, 900 USD, history and food, relaxed."
3. Review the inline itinerary card (map, sources, estimated total) → **Approve & save** → `Saved as TRIP-…`.
4. "Watch that trip." → hourly weather/FX checks start.
5. "What should I prepare?" → tailored pre-travel checklist.

## How the flow works

1. A traveller taps a suggestion chip, types a message with their trip details (place, dates, party, budget), or records a voice note.
2. The Coordinator LLM extracts intent and known details. It asks a targeted question when destination, dates/duration, budget, party composition or travel pace is missing. Child ages are requested when children are part of the party; hotel use is captured when it changes the schedule.
3. The relevant specialized role gathers data via MCP or drafts from those returned facts.
4. The app checks names, source URLs and closed weekdays in code. Ticket estimates come from listed prices and the currency-conversion tool; unknown prices remain explicitly unknown.
5. The UI shows the draft and sources. The traveller approves or rejects it.
6. Approval code—not the LLM—sends the exact approved payload to the simulated Trip Store. Saving is not booking, purchasing, or reserving.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the component diagram and data flow.

## What to demonstrate

1. Ask for a trip with an omitted detail and show the Coordinator asking a concise follow-up.
2. Build an Istanbul itinerary for a family; point out source links, age-aware planning, the map and estimate caveats.
3. Show a known closed day or the synthetic price-conflict overlay and explain how the app avoids presenting one disputed price as certain.
4. Reject a proposed plan and show that no trip was saved; then approve one and show the returned `TRIP-` ID.
5. Use the voice button or a Google Maps coordinate pin and explain the nearby search's straight-line time estimate limitation.
6. Ask about visas and show that the advisor uses official government portals and asks for passport nationality when needed.
7. Add an hourly watch and explain the honest scope: available weather and FX only, not hotel/flight price inventory.

## Presentation talking points

- **Agentic, but bounded:** role separation makes research, planning and verification visible, while code enforces facts and writes.
- **Human approval is a hard gate:** the model never receives a save tool; a matching pending action is required for every write.
- **Evidence over confident prose:** listings, prices and weather are estimates with provenance. Unsupported locations are not invented.
- **Simple structure:** one FastAPI app, small Python modules by responsibility, one existing MCP service, and a static frontend with no frontend build chain.
- **Honest constraints:** replay data covers the kit's cached cities (Istanbul and Amman). Other destinations need live/record mode and external service connectivity. No booking, airline inventory, hotel prices, pharmacy listings, or authoritative venue opening guarantees are available from this kit.

## Run it

1. Copy `.env.example` to `.env` and add `OPENROUTER_API_KEY`. Never commit `.env`.
2. Start both services with `docker compose up --build`, then open `http://localhost:8000`.
3. Or locally: activate a Python 3.12 virtual environment, install `requirements.txt`; start `uvicorn services.travel_api:app --port 8103`, then start `uvicorn app.main:app --port 8000`.
4. Run `python check_kit.py` for the provided gateway/MCP smoke test and `python evals/run_evals.py` for the ten kit cases. Additional scenarios are in `evals/cases.extra.jsonl`.

## Things to notice / limitations

- The data gateway is supplied and remains unchanged. Replay mode is deterministic and offline; live mode is subject to upstream availability, rate limits and data licensing.
- Wikivoyage prices/hours may be stale. Currency conversion is an estimate, and child ticket pricing is not inferred from adult listings.
- Nearby walking minutes are straight-line estimates; use a live map for actual paths and accessibility.
- Official visa requirements depend on nationality, purpose, transit and trip dates. The app is informational, not legal advice; contact an embassy/consulate to confirm unclear cases.
- Voice transcription downloads/loads a local Whisper model and can require substantial disk space. Text chat remains usable if the optional voice dependency is unavailable.
- Session memory and scheduled watches are in-process; restarting the app clears them. A production version should use durable storage and a managed scheduler.
- The eval scorecard has not been run in this workspace because it requires an OpenRouter key and running services. Run the command above after configuring `.env`; report the actual score rather than claiming a pass rate in a presentation.

## Real vs simulated

| Part | Status |
|---|---|
| OpenRouter model | Real external LLM; requires your API key |
| Travel listings, weather, routes, FX | Real open data through the gateway; replay cache by default |
| Trip Store / traveller preferences | Simulated local system |
| Synthetic overlay records | Test-only synthetic data |
| Voice transcription | Local faster-whisper model, optional |
| Booking, flights, hotel prices/payments | Not available; never performed |
