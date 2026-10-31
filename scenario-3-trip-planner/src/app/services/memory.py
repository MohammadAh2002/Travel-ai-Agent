from __future__ import annotations

import time

from ..core.config import SESSION_TTL_SECONDS
from ..core.models import SessionState

SESSIONS: dict[str, tuple[float, SessionState]] = {}


def get_session(session_id: str) -> SessionState:
    now = time.time()
    expired = [key for key, (touched, _) in SESSIONS.items() if now - touched > SESSION_TTL_SECONDS]
    for key in expired:
        SESSIONS.pop(key, None)
    stored = SESSIONS.get(session_id)
    state = stored[1] if stored else SessionState(session_id=session_id)
    SESSIONS[session_id] = (now, state)
    return state


def save_session(state: SessionState) -> None:
    SESSIONS[state.session_id] = (time.time(), state)
