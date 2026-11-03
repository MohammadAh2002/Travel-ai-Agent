"""Durable traveller preferences; seed data never overwrites saved changes on startup."""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3


@contextmanager
def database():
    path = Path(os.getenv("PREFERENCES_DB_PATH", str(
        Path(__file__).resolve().parents[2] / "data" / "preferences.sqlite3"
    ))).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path), timeout=10)) as db:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS travellers (traveller_id TEXT PRIMARY KEY COLLATE NOCASE, data TEXT NOT NULL)")
            yield db


def initialize(travellers: list[dict], *, reset: bool = False) -> None:
    with database() as db:
        if reset:
            db.execute("DELETE FROM travellers")
        db.executemany("INSERT OR IGNORE INTO travellers VALUES (?, ?)",
                       [(t["traveller_id"], json.dumps(t, ensure_ascii=False)) for t in travellers])


def get(traveller_id: str) -> dict | None:
    with database() as db:
        row = db.execute("SELECT data FROM travellers WHERE traveller_id = ?", (traveller_id,)).fetchone()
        return json.loads(row[0]) if row else None


def save(traveller_id: str, preferences: dict, updated_at: str) -> dict:
    with database() as db:
        # Serialize read/merge/write across processes to preserve independent updates.
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT data FROM travellers WHERE traveller_id = ?", (traveller_id,)).fetchone()
        traveller = json.loads(row[0]) if row else {
            "traveller_id": traveller_id, "name": None, "preferences": {}, "updated_at": None,
        }
        traveller["preferences"].update(preferences)
        traveller["updated_at"] = updated_at
        db.execute("INSERT INTO travellers VALUES (?, ?) ON CONFLICT(traveller_id) DO UPDATE SET data = excluded.data",
                   (traveller_id, json.dumps(traveller, ensure_ascii=False)))
        return traveller


def list_travellers() -> list[dict]:
    with database() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT data FROM travellers ORDER BY traveller_id")]
