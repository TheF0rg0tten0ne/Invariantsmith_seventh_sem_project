"""
Explainability store.

Every AI action (detection, suggestion, apply, rejection) gets logged here.
This powers:
  1. The "why did the AI change my code" history panel in the client.
  2. The fine-tuning flywheel: accepted fixes are positive examples,
     rejected/edited fixes are hard negatives for the next training round.
"""
import sqlite3
import json
import time
from contextlib import contextmanager
from typing import Any, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    action_type TEXT NOT NULL,          -- 'analyze' | 'suggest_fix' | 'apply_fix' | 'explain'
    error_type TEXT,                    -- e.g. 'NameError', 'SyntaxError', 'F821'
    error_message TEXT,
    diff TEXT,                          -- unified diff proposed/applied
    rationale TEXT,                     -- short model-generated explanation
    confidence REAL,
    outcome TEXT,                       -- 'accepted' | 'rejected' | 'edited' | NULL (pending)
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_actions_file ON actions(file_path);
CREATE INDEX IF NOT EXISTS idx_actions_session ON actions(session_id);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def log_action(
    session_id: str,
    file_path: str,
    action_type: str,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    diff: Optional[str] = None,
    rationale: Optional[str] = None,
    confidence: Optional[float] = None,
    outcome: Optional[str] = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO actions
               (session_id, file_path, action_type, error_type, error_message,
                diff, rationale, confidence, outcome, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, file_path, action_type, error_type, error_message,
                diff, rationale, confidence, outcome, time.time(),
            ),
        )
        return cur.lastrowid


def update_outcome(action_id: int, outcome: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE actions SET outcome = ? WHERE id = ?", (outcome, action_id))


def get_history(file_path: Optional[str] = None, session_id: Optional[str] = None,
                 limit: int = 100) -> list[dict[str, Any]]:
    query = "SELECT * FROM actions"
    clauses, params = [], []
    if file_path:
        clauses.append("file_path = ?")
        params.append(file_path)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def export_training_pairs(outcome: str = "accepted", limit: int = 10000) -> list[dict[str, Any]]:
    """Pull accepted (or rejected, for hard negatives) fixes for retraining."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT error_type, error_message, diff, rationale, confidence
               FROM actions
               WHERE action_type = 'suggest_fix' AND outcome = ?
               ORDER BY created_at DESC LIMIT ?""",
            (outcome, limit),
        ).fetchall()
        return [dict(r) for r in rows]
