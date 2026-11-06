"""Spaced review scheduling with FSRS (py-fsrs, MIT) — default parameters.

One card per (student, concept). When a study session completes, the
mastery outcome is mapped to an FSRS rating and the card is rescheduled:

    mastered, test all-correct, no hints  -> Easy
    mastered (some hints / minor weakness)-> Good
    passed_with_help                      -> Hard
    needs_review                          -> Again

The mapping is a *design decision*, not something FSRS prescribes; it is
pinned here and covered by tests so it can be debated on evidence.
The FSRS parameter optimizer is deliberately NOT used: it needs hundreds
of review logs to say anything trustworthy. Revisit when the team's
pooled ReviewLogs reach that scale (condition recorded in
docs/implementation-plan.md).

If the fsrs package is unavailable (e.g. a minimal CI image), a small
documented interval fallback keeps reviews working instead of breaking
the app; the scheduler in use is reported by scheduler_name().
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from . import storage

try:
    from fsrs import Card, Rating, Scheduler

    _scheduler = Scheduler()
    FSRS_AVAILABLE = True
except Exception:  # pragma: no cover - exercised via monkeypatch in tests
    FSRS_AVAILABLE = False

_RATING_BY_OUTCOME = {"easy": 4, "good": 3, "hard": 2, "again": 1}
# fallback intervals (days) when fsrs is missing: prev * factor
_FALLBACK = {"again": (1.0, 0.3), "hard": (1.0, 1.2), "good": (2.5, 2.5), "easy": (5.0, 3.5)}


def scheduler_name() -> str:
    return "fsrs" if FSRS_AVAILABLE else "fallback-intervals"


def outcome_for(status: str, evidence: dict) -> str:
    """Map a mastery outcome to a review rating bucket."""
    if status == "mastered":
        if evidence.get("test_all_correct") and not evidence.get("hints_used") \
                and not evidence.get("weak"):
            return "easy"
        return "good"
    if status == "passed_with_help":
        return "hard"
    return "again"


def record_result(student: str, concept_id: str, status: str,
                  evidence: dict, now: float | None = None) -> dict:
    """Reschedule the (student, concept) card after a completed session."""
    now = time.time() if now is None else now
    outcome = outcome_for(status, evidence)
    existing = storage.get_review_card(student, concept_id)
    if FSRS_AVAILABLE:
        card = Card.from_dict(existing["card"]["fsrs"]) if existing and "fsrs" in existing["card"] \
            else Card()
        new_card, _log = _scheduler.review_card(
            card, Rating(_RATING_BY_OUTCOME[outcome]),
            review_datetime=datetime.fromtimestamp(now, tz=timezone.utc))
        due = new_card.due.timestamp()
        state = {"fsrs": new_card.to_dict(), "outcome": outcome}
    else:
        prev = existing["card"].get("interval_days", 0.0) if existing else 0.0
        first, factor = _FALLBACK[outcome]
        interval = first if prev == 0 else max(0.5, prev * factor)
        due = now + interval * 86400
        state = {"interval_days": interval, "outcome": outcome}
    storage.set_review_card(student, concept_id, state, due)
    return {"concept_id": concept_id, "outcome": outcome, "due": due,
            "scheduler": scheduler_name()}


def due_reviews(student: str, now: float | None = None) -> list[dict]:
    """Cards whose review time has arrived, earliest first."""
    now = time.time() if now is None else now
    return [{"concept_id": r["concept_id"], "due": r["due"],
             "last_outcome": r["card"].get("outcome")}
            for r in storage.list_review_cards(student) if r["due"] <= now]


def all_reviews(student: str) -> list[dict]:
    return [{"concept_id": r["concept_id"], "due": r["due"],
             "last_outcome": r["card"].get("outcome")}
            for r in storage.list_review_cards(student)]
