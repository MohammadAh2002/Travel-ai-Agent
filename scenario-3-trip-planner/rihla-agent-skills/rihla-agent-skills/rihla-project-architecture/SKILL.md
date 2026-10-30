---
name: rihla-project-architecture
description: Use when exploring, extending, refactoring, or debugging the Rihla travel-agent repository. Enforces understanding of the existing API, MCP server, CrewAI app, data modes, contracts, and bootcamp constraints before making changes.
---

# Rihla project architecture

## Goal
Make safe, incremental changes to Rihla without breaking the supplied travel API, hidden-test assumptions, or existing bootcamp requirements.

## Before changing code
1. Inspect the repository tree, README, `.env.example`, API contract, CrewAI setup, MCP tools, evaluation cases, and Docker Compose.
2. Trace the actual request path: UI -> app API -> CrewAI workflow -> MCP client -> travel MCP server -> travel API -> Trip Store.
3. Identify which code belongs to the supplied kit and which code belongs to the team's application. Do not modify protected/simulated kit behavior unless the user explicitly authorizes it and doing so does not violate the brief.
4. Read relevant tests before implementation. Confirm package versions from the repository; do not upgrade dependencies casually.
5. Write a short implementation plan naming files, contract changes, tests, and risks before broad refactors.

## Project facts to preserve
- Travel reads use real open-data sources through replay/live/record modes.
- The Trip Store and travellers are simulated.
- The application must not claim to book or purchase anything.
- The app must use the supplied MCP server for the client's system.
- Preserve the API contract, source citations, memory, guardrails, approval gate, and callable entry point.
- Keep secrets out of source control; use environment variables and `.env.example`.

## Engineering rules
- Prefer small, reversible changes over rewrites.
- Reuse existing adapters, schemas, error types, and utilities.
- Keep business rules out of UI components and LLM prompts where deterministic code is appropriate.
- Do not invent endpoints, fields, MCP tools, cached data, or external capabilities. Verify them in code/docs.
- Preserve backward compatibility unless a contract change is intentional and documented.
- After changes, run focused tests, the full relevant evaluation suite, and startup/smoke checks.

## Completion report
Summarize changed files, behavior, tests run and results, known limitations, and any manual verification still needed.
