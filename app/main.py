"""HTTP API + static web UI (Group C owns the wiring).

Run:  uvicorn app.main:app --reload   then open http://127.0.0.1:8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import knowledge, storage, tutor

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Guided Learning Agent — 三极管放大电路")

storage.init_db()


class StartSession(BaseModel):
    student: str = Field(min_length=1, max_length=40)
    concept_id: str


class AnswerIn(BaseModel):
    option_index: int
    confidence: int | None = Field(default=None, ge=1, le=5)


@app.get("/api/course")
def course():
    return knowledge.COURSE | {"concepts": knowledge.list_concepts()}


@app.get("/api/progress/{student}")
def progress(student: str):
    return {"student": student, "mastery": storage.get_progress(student)}


@app.post("/api/sessions")
def start(payload: StartSession):
    try:
        return tutor.start_session(payload.student.strip(), payload.concept_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    session = storage.get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    return {"session": session, "events": storage.list_events(session_id)}


@app.post("/api/sessions/{session_id}/hint")
def hint(session_id: str):
    try:
        return tutor.request_hint(session_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sessions/{session_id}/answer")
def answer(session_id: str, payload: AnswerIn):
    try:
        return tutor.answer(session_id, payload.option_index, payload.confidence)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
