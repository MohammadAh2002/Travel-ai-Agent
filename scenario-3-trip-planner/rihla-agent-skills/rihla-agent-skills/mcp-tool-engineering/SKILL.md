---
name: mcp-tool-engineering
description: Use when adding, modifying, documenting, or debugging MCP client/server tools or connecting CrewAI agents to Rihla's supplied travel MCP server.
---

# MCP tool engineering

## Goal
Make tools easy for an LLM to select correctly, safe to call, predictable to parse, and robust under failures.

## Rules
1. Inspect the actual MCP server and enumerate its current tools and schemas before writing client code.
2. Use the supplied MCP server for the simulated travel system. Do not bypass it with direct REST calls from the agent when the brief requires MCP.
3. Keep tool names and descriptions specific. Describe when to call the tool, required inputs, units, supported values, and what it does not provide.
4. Validate arguments before calls. Normalize user-facing names carefully, but do not fabricate IDs or place records.
5. Parse the complete tool result and preserve `ok`, error code, message, status, provenance, and relevant metadata.
6. Treat tool errors as data to explain or recover from, not as empty successful results.
7. Apply bounded timeouts and retries only where safe. Do not retry non-idempotent writes blindly.
8. Keep write tools such as `save_trip` unavailable to the LLM. Writes must go through the application's approval endpoint.
9. Log tool name, duration, outcome, and correlation/session ID without logging secrets or unnecessary personal data.
10. Avoid excessive tool calls. Cache/reuse results within a planning run when appropriate and respect upstream rate limits.

## Rihla tools to understand
Review the supplied tools for geocoding, attractions, restaurants, opening hours, weather, currency conversion, route time, trip saving, trip retrieval, and traveller preferences. Do not assume this list or its schemas are unchanged; inspect the running repository.

## Tests
Add tests for valid calls, invalid arguments, unknown places, not-cached results, 4xx/5xx responses, timeouts, malformed tool output, and duplicate write prevention.
