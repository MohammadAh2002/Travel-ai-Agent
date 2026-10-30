---
name: crewai-orchestration-design
description: Use when designing or changing Rihla's CrewAI agents, tasks, crews, flows, state, delegation, structured outputs, or multi-agent orchestration.
---

# CrewAI orchestration design

## Goal
Use the smallest clear agent workflow that improves travel-plan quality. Do not add agents merely to make the architecture look more complex.

## Workflow
1. Inspect the installed CrewAI version and current implementation. Follow the APIs supported by the pinned version; do not copy examples from a different version without checking compatibility.
2. Define each agent's distinct responsibility, inputs, outputs, tools, and stopping condition.
3. Define the workflow state explicitly: traveller identity, conversation/session context, preferences, trip constraints, researched evidence, draft itinerary, validation findings, pending action, and approval status.
4. Use Pydantic or the project's existing schema approach for structured outputs.
5. Keep deterministic sequencing and hard constraints in code. Use an LLM where interpretation, research planning, or qualitative judgement is genuinely needed.
6. Bound delegation, retries, iterations, token use, and execution time.
7. Ensure failures and partial results are represented explicitly; do not silently convert tool errors into plausible travel facts.

## Rihla role boundaries
Possible roles include:
- Research: discover candidate places and collect source-backed facts.
- Scheduling: propose a feasible ordering using opening hours and route data.
- Budget: calculate and explain estimated costs.
- Critic: identify itinerary defects and cite the evidence for each finding.
- Replanning: revise only affected parts after a changed condition or user constraint.

Only introduce a role when it has a distinct task and measurable benefit. Avoid multiple agents independently making the same API calls.

## Output requirements
Prefer typed outputs with explicit fields such as `status`, `findings`, `evidence`, `assumptions`, `unresolved_questions`, and `proposed_changes`.

## Tests
Test role boundaries, missing inputs, tool errors, malformed outputs, iteration limits, and whether the crew asks for clarification when essential trip details are absent.
