"""Application entry point: ``uvicorn app.main:app`` (run from ``src/``).

The app is split into sub-packages by responsibility:

- ``app/api``       FastAPI app, endpoints and the approval gate
- ``app/chat``      chat_flow orchestration + deterministic itinerary helpers
- ``app/agents``    CrewAI roles; each role's skill lives in ``agents/skills/<role>.md``
- ``app/services``  MCP client, session memory, watch jobs
- ``app/features``  checklist, nearby/maps, voice transcription
- ``app/core``      config, models, guardrails
"""

from .api import app

__all__ = ["app"]
