# Rihla — project summary and how everything works

Rihla is a conversational trip-planning crew. A traveller chats with it in a browser, a team of ten CrewAI
roles researches sourced activities and drafts a day-by-day itinerary, and the plan is saved only after
the traveller explicitly approves it. Nothing is ever booked or purchased — saving stores a plan.

## What we have

```text
scenario-3-trip-planner/
├── Dockerfile, docker-compose.yml   # build/run both services from the project root
├── .env, .env.gemini, .env.openrouter, .env.example   # config + provider keys (gitignored)
├── README.md, SUMMARY.md, ARCHITECTURE.md
│
├── src/                   # ALL OUR CODE
│   ├── requirements.txt   # app dependencies
│   ├── app/
│   │   ├── main.py        # entry point — re-exports the FastAPI app (uvicorn app.main:app)
│   │   ├── api/app.py     # FastAPI app, all HTTP endpoints, the hard approval gate
│   │   ├── chat/
│   │   │   ├── flow.py        # chat_flow: orchestration per intent, profile helpers, replies
│   │   │   └── itinerary.py   # deterministic work: sanitise drafts, verify hours/costs, routes
│   │   ├── agents/
│   │   │   ├── crew.py        # CrewAI runtime: loads skill files, runs bounded tasks
│   │   │   ├── coordinator.py # intent classification + detail extraction
│   │   │   ├── researcher.py  # MCP evidence gathering
│   │   │   ├── planner.py     # draft task list: researcher → budget → planner/reviser
│   │   │   ├── verifier.py    # independent critic check
│   │   │   ├── docs_advisor.py# official-source document answers
│   │   │   ├── budget.py      # deterministic budget-summary wording
│   │   │   └── skills/        # ONE FILE PER AGENT — the role's skill (see below)
│   │   │       ├── coordinator.md · place_researcher.md · lodging_advisor.md
│   │   │       ├── weather_analyst.md · route_mobility_analyst.md · budget_analyst.md
│   │   │       ├── itinerary_planner.md · revision_specialist.md
│   │   │       └── documents_advisor.md · itinerary_critic.md
│   │   ├── services/
│   │   │   ├── mcp_client.py  # MCP stdio client → kit's services/travel_mcp.py
│   │   │   ├── memory.py      # user sessions — in-process dict, 24 h TTL (details below)
│   │   │   └── watches.py     # hourly weather/currency watch jobs (in-process)
│   │   ├── features/
│   │   │   ├── checklist.py   # tailored pre-travel checklist items
│   │   │   ├── nearby.py      # nearby places around a pin / Maps link
│   │   │   ├── map_tools.py   # coordinate + Maps-link parsing, haversine distance
│   │   │   └── voice.py       # faster-whisper local transcription
│   │   ├── core/
│   │   │   ├── config.py      # .env discovery + all settings (model, keys, TTLs)
│   │   │   ├── models.py      # pydantic types: TravelerProfile, SessionState, requests
│   │   │   └── guardrails.py  # input screening and output link stripping
│   │   ├── data/travel_docs.json  # official-government document source directory
│   │   └── static/            # index.html, app.js, style.css — no-build browser UI
│   ├── tests/test_core.py     # 23 unit tests
│   └── evals/cases.extra.jsonl# our extra eval scenarios
│
└── kit/                   # PROVIDED FILES — unchanged
    ├── services/              # travel gateway (:8103) + MCP server + data cache
    ├── evals/                 # provided eval runner + cases + generated scorecards
    ├── ui/app_ui.py           # provided Gradio demo client
    ├── check_kit.py           # provided smoke test
    ├── requirements.txt       # kit deps
    └── .venv/                 # local virtual environment
```

## What each agent's skill file does

Every CrewAI role has its own Markdown file under `src/app/agents/skills/<role>.md`. Each file contains a
small front-matter block (`role`, `goal`, `backstory` — the CrewAI `Agent` identity) followed by the
skill body: that role's standing rules (e.g. *never invent places*, *hotel suggestions are unverified*,
*distinguish forecasts from seasonal normals*). At startup `crew.py` parses all ten files into
`ROLE_SPECS`; when a task runs, the matching skill body is automatically prepended to the task-specific
instructions, so a role always works from its own written skill. To change an agent's behaviour you edit
its `.md` file — no Python change needed.

## How the workflow goes (one chat message, end to end)

1. **Intake** — the browser posts `{session_id, message, user?}` to `/api/chat` (`src/app/api/app.py`), which
   hands off to `chat_flow` (`src/app/chat/flow.py`).
2. **Guardrails** — `inspect_input` blocks >5 000-char messages and prompt-injection attempts.
3. **Session load** — `get_session` pulls the in-memory `SessionState`: conversation history, traveller
   profile, current itinerary, any pending action.
4. **Coordinator** — the Coordinator/Clarifier role (skill: `skills/coordinator.md`) returns a JSON
   object: `intent` plus every trip detail it could extract. Intents: `itinerary`, `day_plan`, `revise`,
   `documents`, `nearby`, `lodging`, `weather`, `route`, `checklist`, `price`, `watch`, `remember`,
   `general`, and `off_topic`.
5. **General / off-topic** — `general` and `off_topic` intents go to the General Knowledge Agent
   (`general_agent`), which answers any question using live web-search results (DuckDuckGo) gathered
   in code, then cites the sources it used. If the web lookup or the crew call fails, the app falls
   back to a fixed capability reply.
6. **Clarify first** — for itinerary intents, `missing_trip_info` checks the essentials (destination,
   dates/days, budget, party size, children's ages). Anything missing → one focused question back, and
   the turn ends.
7. **Research** — `researcher.py` calls MCP tools (`find_attractions`, `find_restaurants`,
   `get_weather`, plus `get_preferences` for known travellers). Results are treated as untrusted
   evidence; synthetic listings are dropped by `trim_research`.
8. **Draft** — `planner.py` runs the evidence chain: Place Researcher → Budget Analyst → (Lodging
   Advisor only if lodging matters) → Itinerary Planner, or the Revision Specialist when revising.
9. **Verify in code** — `itinerary.py` does the deterministic work the LLM can't be trusted with:
   `verify_selected_hours` re-checks opening hours per venue, `estimate_routes` measures walking legs,
   `verify_costs` converts listed prices through the FX tool, and `sanitize_itinerary` drops unknown
   places, keeps venues off closed days (relocating them into open gaps), validates times, and sums
   only verified prices. A failed first pass triggers one repair retry.
10. **Critic** — the independent Itinerary Critic checks the sanitised draft against the research.
    Approved → the plan becomes a `pending_action` and renders as an approve/reject card in the UI.
11. **Approval gate** — `/api/approve` compares the clicked action ID with the session's exact pending
    action, then writes that payload through MCP (`save_trip` uses the action ID as idempotency key —
    double-approving can't save twice). Reject writes nothing. No CrewAI role ever holds a write tool.
12. **Specialist intents** — `documents` (official government refs only), `weather`, `route`, `nearby`,
    `price`, `checklist`, `remember` (preference save also requires approval), `watch` (hourly job) each
    follow the same pattern: clarify → tool evidence → specialist answer → no silent writes.

## Where user data is stored

| What | Where | Lifetime |
|---|---|---|
| **User sessions** | `src/app/services/memory.py` stores serialized `SessionState` records in `data/sessions.sqlite3` (override with `SESSION_DB_PATH`). Activity refreshes the timestamp; `SESSION_TTL_SECONDS` defaults to 86 400 s (24 h). | Survives app restart; expires after the inactivity TTL. |
| **Session ID itself** | Created by the browser (`web-<uuid>`) in `src/app/static/app.js`, sent with every request. | Per conversation in the browser. |
| **Chat list UI** | `localStorage["rihla.conversations.v1"]` — the sidebar history you see is purely a browser-side cache for display. | Until the user clears browser storage; independent of server state. |
| **Approved trips** | The simulated Trip Store, written only via MCP `save_trip` by `/api/approve` code — never by the LLM. | In-process inside the travel gateway; cleared on gateway restart/reset. |
| **Saved preferences** | Gateway SQLite database `data/preferences.sqlite3` (`PREFERENCES_DB_PATH` override), via MCP `save_preferences` after explicit approval. | Survives gateway restart; test-only `/admin/reset` restores seed data. |
| **Watches** | `src/app/services/watches.py` module-level `WATCHES` dict (max 10 per session), refreshed by a background asyncio loop every `WATCH_INTERVAL_SECONDS` (default 3 600 s). | In-process; cleared on restart. |

Practical takeaway: sessions survive app restarts in SQLite until their inactivity TTL expires.
Watches clear on app restart. Preferences survive gateway restart in SQLite; `/admin/reset` clears them.
Approved trips remain in gateway process memory and are lost on gateway restart/reset.

## Features

- Multi-day itineraries (≤14 days) and one-day plans with times, walking minutes, sources and a Leaflet map.
- Conversational revision — "make day 2 more relaxed" — always as a new approval-gated proposal.
- Hard approval gate for every write; idempotent saves.
- Price checks that show source disagreement instead of one confident number.
- Nearby places from a Google Maps link or raw coordinates (straight-line walking estimates).
- Travel-document answers citing official government portals only.
- Pre-travel checklists tailored to destination, party and gift-heavy trips.
- Preference memory (diet, interests, walking limits) — saved only after approval.
- Hourly weather/currency watches with honest scope (no hotel/flight feeds exist).
- Voice input via local faster-whisper; guardrails against injection and over-length input.
- A web-backed general agent answers questions outside the travel scope, citing live search results.

## How it was built (and how to change it)

- **Provider-agnostic LLM**: `.env` (project root) sets `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`,
  `MODEL` — Gemini free tier and OpenRouter both work; nothing in the code is provider-specific.
  `config.py` finds `.env` at the project root first, then `kit/.env` as a fallback.
- **Agents are configuration, not code**: edit `src/app/agents/skills/<role>.md` to change a role's
  behaviour. New roles need a `.md` file plus a call site; `ROLE_SPECS` keys come from filenames.
- **Determinism where it matters**: arithmetic, scheduling, hours checks and all writes are Python;
  the LLM classifies, selects, drafts, explains and criticises.
- **Trust boundaries**: tool results are untrusted evidence; no agent can save; reply URLs are stripped
  unless they came from a tool result.

## Run it

1. Put a key in `.env` at the project root (Gemini block active by default; OpenRouter block commented).
2. `docker compose up --build` → open `http://localhost:8000`.
3. Or locally (Python 3.12, `pip install -r src/requirements.txt`; the kit's `.venv` already has everything):
   - gateway: `cd kit && uvicorn services.travel_api:app --port 8103`
   - app: `cd src && uvicorn app.main:app --port 8000`
4. Verify: `cd src && python -m unittest tests.test_core` (23 unit tests),
   `python kit/check_kit.py` (kit smoke test), `python kit/evals/run_evals.py` (API-level cases;
   our extra scenarios are in `src/evals/cases.extra.jsonl`).

## Honest limits

- Replay data covers the kit's cached cities (Istanbul, Amman); other destinations need live/record mode.
- Sessions and watches are in-process; a production version needs durable storage and a scheduler.
- Listed prices/hours can be stale; conversions are estimates; child pricing is not inferred.
- No booking, live hotel rates/availability, flight data, pharmacy listings, or legal eligibility determination. Hotel suggestions come from live web search and are unverified.
