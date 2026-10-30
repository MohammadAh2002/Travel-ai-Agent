---
name: agent-evaluation-observability
description: Use when adding evaluation cases, debugging agent behavior, measuring Rihla quality, adding traces/logging, or documenting before-and-after improvements.
---

# Agent evaluation and observability

## Goal
Make agent quality measurable and failures diagnosable. A feature is not complete until its expected behavior is tested.

## Evaluation-driven workflow
1. Identify the behavior gap before writing a large implementation.
2. Add a reproducible evaluation case that fails for the right reason.
3. Record the baseline result.
4. Implement the smallest fix.
5. Re-run the case and the full relevant suite.
6. Record before/after results and any regressions.

## Rihla evaluation coverage
Maintain at least the required sample cases and add cases for:
- Rain/weather replanning.
- Walking and pace constraints.
- Multiple schedule conflicts.
- Unknown or stale opening hours/prices.
- Conflicting source values.
- Partial MCP/API outage.
- Malformed model output.
- Prompt injection in retrieved listings.
- User rejection and approval.
- Duplicate approval/idempotency.
- Preference memory across sessions.
- Clarification when dates or budget are missing.

## Metrics
Track separately:
- Hard-constraint satisfaction.
- Schedule conflict rate.
- Budget compliance.
- Citation/provenance coverage.
- Unsupported-claim rate.
- Recovery success.
- Tool-call success and latency.
- End-to-end latency and model/token cost.
- Approval-boundary violations (target: zero).

Do not collapse everything into one score without showing component metrics and denominators.

## Observability
Log structured events with run/session ID, agent/task, tool name, duration, outcome, retry count, and error code. Redact credentials and unnecessary personal data. Make it possible to reconstruct why a recommendation was made.

## Completion
Update the README scorecard with exact test counts, pass rates, a documented failure fixed, and known limitations. Never claim tests passed unless they were run.
