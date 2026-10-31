# Rihla — Travel, thoughtfully planned

Rihla is a travel-planning crew that asks what it needs, researches sourced activities, and leaves itinerary decisions and saving in the traveller's hands. It is built on the provided Scenario 3 travel gateway and MCP server.

> **Nothing is booked or purchased.** A saved itinerary is only stored in the simulated Rihla Trip Store. Prices and routes are estimates.

## What makes it useful

- Conversational clarification for dates, budget, party size and children's ages, pace, interests and hotel use.
- Ten focused CrewAI roles, routed only when relevant: Coordinator/Clarifier, Place Researcher, Lodging Advisor, Weather Analyst, Route & Mobility Analyst, Budget Analyst, Itinerary Planner, Revision Specialist, Documents Advisor and independent Itinerary Critic.
- Sourced day plans with itinerary revisions, opening-day checks, converted listed ticket estimates and disclosed uncertainty.
- Quick-start suggestion chips for trip preparation, official travel-document links, one-day planning, nearby places, trip plans and hourly watches — everything is done in chat.
- Google Maps coordinate pins and supported Google Maps links for approximate nearby search.
- Voice input with local faster-whisper speech-to-text.
- Traveller preference memory and explicit approval for saved changes.
- A hard approval gate for trip saves, using the approved action ID as the idempotency key.
- Chat-first responsive web UI: trip details (dates, budget, party size) are collected conversationally, and itineraries render as inline cards with source citations, a map and approve/reject controls.

## Run the app

### Docker Compose

1. Copy `.env.example` to `.env`.
2. Set `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, and `MODEL` in `.env` for your OpenAI-compatible provider. Do not commit this file.
3. Start the travel gateway and app:

```powershell
docker compose up --build
```

Open `http://localhost:8000`. Replay mode serves cached Istanbul and Amman data by default. The gateway API is on `http://localhost:8103`.

### Local Python

Use Python 3.12. The existing `kit\.venv` already has all dependencies (`pip install -r src\requirements.txt` covers the app). Activate it, then open two terminals:

```powershell
kit\.venv\Scripts\activate
cd kit
uvicorn services.travel_api:app --port 8103
```

```powershell
kit\.venv\Scripts\activate
cd src
uvicorn app.main:app --port 8000
```

Visit `http://localhost:8000`. `GET /health` reports whether the model key is configured.
The simulated gateway defaults to `dev-key-change-me`. If you replace `TRAVEL_API_KEY` in `.env`, also export that same value in the shell used to start the gateway; the provided gateway reads its key from the process environment.

## API and evaluation

The app implements `POST /api/chat`, `POST /api/approve`, `POST /api/voice` and `GET /health`. Optional hourly watch endpoints are `POST /api/watch`, `GET /api/watch/{session_id}` and `DELETE /api/watch/{watch_id}`.

Run the supplied gateway/MCP smoke test and the ten brief cases after starting the gateway and app:

```powershell
python kit/check_kit.py
python kit/evals/run_evals.py
python kit/evals/run_evals.py --cases src/evals/cases.extra.jsonl -v
```

Unit tests (no gateway needed): `cd src && python -m unittest tests.test_core`

The eval runner can write a scorecard with `--out evals/scorecard.md`. It calls the configured model provider and requires the travel gateway and app to be running. Report only the score actually produced; these unit and smoke checks are not a substitute for the LLM-backed scorecard.

### Current scorecard status

| Measure | Status |
|---|---|
| Kit API/MCP smoke test | Passed in this workspace |
| Local unit tests | 18 passed |
| Kit sample cases | Not run in this verification session |
| Additional cases | Not run in this verification session |
| Before/after fix | Before: an LLM draft could include unsupported place names or a listing-closed weekday. After: code keeps only MCP-returned places, replaces source URLs from those tool results, queries opening hours for selected stops, and filters closed-day/timing conflicts before the approval proposal. |

## Architecture

```mermaid
flowchart LR
  Browser -->|chat / voice / approve| FastAPI
  FastAPI --> Coordinator[Trip Coordinator / Clarifier]
  Coordinator -->|itinerary request| PlaceResearcher[Place Researcher]
  PlaceResearcher --> Budget[Budget Analyst]
  Budget --> Lodging[Lodging Advisor when relevant]
  Lodging --> Planner[Itinerary Planner or Revision Specialist]
  Planner --> Route[Route & Mobility Analyst]
  Route --> Critic[Independent Itinerary Critic]
  Coordinator -->|documents question| Documents[Documents Advisor]
  Coordinator -->|hotel question| Lodging
  Coordinator -->|weather question| Weather[Weather Analyst]
  Coordinator -->|route question| Route
  PlaceResearcher --> MCP
  MCP --> KitMCP[Provided MCP server]
  KitMCP --> Gateway[Provided travel gateway]
  Critic --> Pending[pending_action]
  Pending -->|traveller approves| Gate[Code approval gate]
  Gate -->|idempotent MCP write| Store[Simulated Trip Store]
  FastAPI --> Watches[Weather and FX watches]
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full request flow, and [`SUMMARY.md`](SUMMARY.md) for the presentation checklist and implementation notes.

## Repository map

| Path | Responsibility |
|---|---|
| `src/app/main.py` | Entry point — re-exports the FastAPI app (`uvicorn app.main:app`) |
| `src/app/api/` | FastAPI endpoints and the approval gate |
| `src/app/chat/` | `chat_flow` orchestration + deterministic itinerary verification |
| `src/app/agents/` | Intent-routed CrewAI roles and MCP-backed helpers |
| `src/app/agents/skills/` | One Markdown skill file per CrewAI role, loaded at startup |
| `src/app/services/` | MCP client, session memory, hourly watch jobs |
| `src/app/core/` | Config (`.env` discovery), models, guardrails |
| `src/app/features/` | Voice, Maps/nearby search, pre-trip checklist |
| `src/app/static/` | Single-page UI (HTML, CSS and JavaScript) |
| `src/app/data/travel_docs.json` | Official government references used for document questions |
| `src/tests/` | Unit tests |
| `src/evals/` | Our extra eval scenarios |
| `kit/services/` | Provided simulated gateway and MCP server; unchanged |
| `kit/evals/` | Provided ten cases and the eval runner |

## What is real and what is simulated?

| Component | Details |
|---|---|
| LLM | Real OpenAI-compatible provider, configured by base URL/model/key |
| Agent orchestration | CrewAI 1.15.31; ten specialized roles, with only relevant roles run per request |
| Places and routes | Real open data through the kit's gateway; replay cache by default |
| Weather and currency | Open-Meteo and ECB-based data through the gateway |
| Trip Store and traveller profiles | Simulated local system |
| Test overlays | Synthetic data for evaluation only |
| Voice | Local faster-whisper model; downloads/loads on first use |
| Flights, hotel rates, reservations and payments | Not provided and never performed |

## Honest limitations

- Replay mode only has the kit's Istanbul and Amman cache. Other destinations require network access and `TRAVEL_MODE=live` or `record`.
- Wikivoyage listing prices and hours can be stale; official venue details should be rechecked. Estimates don't promise a trip will fit its budget.
- Adult ticket prices are not child prices. Unknown prices are omitted from totals.
- Nearby distance is a straight-line walking-time estimate, not routed navigation. This data kit has no pharmacy listings.
- Visa and entry rules depend on passport nationality, trip purpose, transit and travel dates. The advisor is informational, not legal advice; confirm uncertain cases with the relevant embassy or consulate.
- Watches can check the gateway's weather/FX data. No hotel or flight pricing feed exists.
- The Lodging Advisor can use hotel details the traveller provides to reason about itinerary impact, but cannot search, compare, price, or book hotels because the kit has no hotel inventory API.
- Session state and watches live in process memory and clear on restart. Production deployment should use durable storage and a managed scheduler.
- Voice requires microphone permission and a compatible faster-whisper install; normal text chat still works without voice.

## Attribution

Travel data is provided by the kit: Wikivoyage (CC BY-SA 4.0), OpenStreetMap contributors (ODbL), Open-Meteo (CC BY 4.0), and European Central Bank reference rates via Frankfurter. Keep source citations and licence attribution when redistributing derived data.
