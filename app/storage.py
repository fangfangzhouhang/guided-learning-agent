"""Learner-state storage (SQLite).

Group C (product engineering) owns this module. It only *records* evidence:
sessions, answers, hints used, error types, confidence calibration.
It never decides mastery by itself — that judgment belongs to tutor.py.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                student TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                hints_used INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'in_progress',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mastery (
                student TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                status TEXT NOT NULL,
                evidence TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (student, concept_id)
            );
            """
        )


def create_session(student: str, concept_id: str) -> dict:
    session_id = uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, student, concept_id, stage, created_at)"
            " VALUES (?, ?, ?, 'diagnose', ?)",
            (session_id, student, concept_id, time.time()),
        )
    record_event(session_id, "session_started", {"concept_id": concept_id})
    return get_session(session_id)


def get_session(session_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def update_session(session_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _conn() as conn:
        conn.execute(
            f"UPDATE sessions SET {cols} WHERE id = ?",
            (*fields.values(), session_id),
        )


def record_event(session_id: str, kind: str, payload: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO events (session_id, kind, payload, created_at)"
            " VALUES (?, ?, ?, ?)",
            (session_id, kind, json.dumps(payload, ensure_ascii=False), time.time()),
        )


def list_events(session_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT kind, payload, created_at FROM events"
            " WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [
        {"kind": r["kind"], "payload": json.loads(r["payload"]), "at": r["created_at"]}
        for r in rows
    ]


def set_mastery(student: str, concept_id: str, status: str, evidence: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO mastery (student, concept_id, status, evidence, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(student, concept_id) DO UPDATE SET"
            " status = excluded.status, evidence = excluded.evidence,"
            " updated_at = excluded.updated_at",
            (student, concept_id, status, json.dumps(evidence, ensure_ascii=False), time.time()),
        )


def get_progress(student: str) -> dict:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT concept_id, status, evidence FROM mastery WHERE student = ?",
            (student,),
        ).fetchall()
    return {
        r["concept_id"]: {"status": r["status"], "evidence": json.loads(r["evidence"])}
        for r in rows
    }
