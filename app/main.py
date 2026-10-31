"""HTTP API + static web UI (Group C owns the wiring).

Run:  uvicorn app.main:app --reload   then open http://127.0.0.1:8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import knowledge, llm, storage, tutor

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Guided Learning Agent — 现电 · 三极管放大电路")

storage.init_db()

print(f"[gla] teacher LLM: {'ON (' + llm.MODEL + ')' if llm.enabled() else 'OFFLINE — no key read'}"
      f" | .env present: {llm.ENV_PATH.exists()} | key configured: {bool(llm.API_KEY)}")


class StartSession(BaseModel):
    student: str = Field(min_length=1, max_length=40)
    concept_id: str


class AnswerIn(BaseModel):
    option_index: int | None = None
    value: float | None = None
    text: str | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)


class ChatIn(BaseModel):
    student: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=2000)


@app.get("/api/status")
def status():
    # Diagnostics expose booleans only — never the key itself.
    return {
        "llm_enabled": llm.enabled(),
        "llm_model": llm.MODEL if llm.enabled() else None,
        "env_file_present": llm.ENV_PATH.exists(),
        "key_configured": bool(llm.API_KEY),
    }


@app.get("/api/courses")
def courses():
    return {"courses": knowledge.list_courses()}


@app.get("/api/course")
def course():
    return knowledge.COURSE | {"concepts": knowledge.list_concepts(),
                                "courses": knowledge.list_courses()}


@app.get("/api/progress/{student}")
def progress(student: str):
    return {"student": student, "mastery": storage.get_progress(student)}


@app.get("/api/profile/{student}")
def profile(student: str):
    return tutor.profile(student)


@app.post("/api/chat")
def chat(payload: ChatIn):
    return tutor.teacher_chat(payload.student.strip(), payload.message.strip())


@app.get("/api/chat/{student}")
def chat_history(student: str):
    return {"student": student, "messages": storage.recent_chat(student, limit=50)}


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
        return tutor.answer(session_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
