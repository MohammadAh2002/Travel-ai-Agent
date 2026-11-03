from __future__ import annotations

import sqlite3
import time
from contextlib import closing, contextmanager

from ..core.config import SESSION_DB_PATH, SESSION_TTL_SECONDS
from ..core.models import SessionState

@contextmanager
def _database():
    SESSION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(SESSION_DB_PATH), timeout=10)) as db:
        with db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    touched REAL NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS sessions_touched ON sessions(touched)")
            yield db


def get_session(session_id: str) -> SessionState:
    now = time.time()
    with _database() as db:
        db.execute("DELETE FROM sessions WHERE touched < ?", (now - SESSION_TTL_SECONDS,))
        stored = db.execute("SELECT data FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        state = SessionState.model_validate_json(stored[0]) if stored else SessionState(session_id=session_id)
        _store(db, state, now)
    return state


def save_session(state: SessionState) -> None:
    with _database() as db:
        _store(db, state, time.time())


def _store(db: sqlite3.Connection, state: SessionState, touched: float) -> None:
    db.execute("""
        INSERT INTO sessions (session_id, data, touched) VALUES (?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET data = excluded.data, touched = excluded.touched
    """, (state.session_id, state.model_dump_json(), touched))
