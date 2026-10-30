# Rihla coding-agent skills

These are development skills for a coding agent working on the Rihla repository. They are not additional runtime CrewAI agents.

## Included skills
- `rihla-project-architecture`
- `crewai-orchestration-design`
- `mcp-tool-engineering`
- `travel-data-provenance`
- `itinerary-constraint-engine`
- `itinerary-critic-agent`
- `adaptive-trip-replanning`
- `approval-security-guardrails`
- `agent-evaluation-observability`
- `travel-agent-ui-ux`

## Installation
Copy the skill folders into the skills directory supported by your coding agent. For an Agent Skills-compatible setup, each skill folder must contain `SKILL.md`.

Examples of possible locations vary by tool:
- `.agents/skills/`
- `.claude/skills/`
- `.codex/skills/`

Check your coding agent's current documentation for the exact discovery path. Do not copy all the SKILL.md contents into one giant system prompt; skills are intended to be loaded when relevant.

## Suggested use
Ask your coding agent to inspect the repository and identify which skills apply before making changes. Have it implement one focused improvement at a time, add or update evaluations, run tests, and report exact results.

The skills are tailored to the Rihla project description supplied in this conversation. The coding agent must still inspect the actual repository and pinned dependency versions before editing code.
