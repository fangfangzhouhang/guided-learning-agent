"""FSRS review-scheduling tests: outcome mapping, due queue, integration."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import knowledge, review, storage, tutor  # noqa: E402


@pytest.fixture()
def fresh_db(tmp_path):
    old = storage.DB_PATH
    storage.DB_PATH = tmp_path / "review.db"
    storage.init_db()
    yield
    storage.DB_PATH = old


def test_outcome_mapping():
    assert review.outcome_for("mastered",
                              {"test_all_correct": True, "hints_used": 0, "weak": False}) == "easy"
    assert review.outcome_for("mastered",
                              {"test_all_correct": True, "hints_used": 2, "weak": False}) == "good"
    assert review.outcome_for("passed_with_help", {}) == "hard"
    assert review.outcome_for("needs_review", {}) == "again"


def test_easy_schedules_later_than_again(fresh_db):
    now = time.time()
    easy = review.record_result("s", "c_easy", "mastered",
                                {"test_all_correct": True, "hints_used": 0, "weak": False}, now=now)
    again = review.record_result("s", "c_again", "needs_review", {}, now=now)
    assert easy["due"] > again["due"] > now


def test_due_queue_lists_only_due(fresh_db):
    now = time.time()
    review.record_result("s", "c1", "needs_review", {}, now=now)
    assert review.due_reviews("s", now=now) == []          # scheduled ahead
    assert len(review.due_reviews("s", now=now + 40 * 86400)) == 1  # due later
    assert review.due_reviews("someone-else", now=now + 40 * 86400) == []


def test_fallback_scheduler_also_works(fresh_db, monkeypatch):
    monkeypatch.setattr(review, "FSRS_AVAILABLE", False)
    now = time.time()
    r1 = review.record_result("s", "c1", "mastered",
                              {"test_all_correct": True, "hints_used": 0, "weak": False}, now=now)
    assert r1["scheduler"] == "fallback-intervals" and r1["due"] > now
    r2 = review.record_result("s", "c1", "needs_review", {}, now=r1["due"])
    assert r2["outcome"] == "again"


def _payload_for(q, correct=True):
    if q.get("type", "mcq") == "mcq":
        idx = next(i for i, o in enumerate(q["options"]) if bool(o.get("correct")) == correct)
        return {"option_index": idx}
    if q.get("type") == "numeric":
        return {"value": q["answer"] if correct else q["answer"] + 10 * q["tolerance"] + 1}
    return {"text": " ".join(g[0] for g in q["rubric_groups"]) + " " + q["model_answer"]
            if correct else "不知道"}


def test_completing_a_concept_creates_a_review_card(fresh_db):
    s = tutor.start_session("stu", "bjt_basics")
    sid = s["session"]["id"]
    for _ in range(40):
        sess = storage.get_session(sid)
        if sess["status"] != "in_progress":
            break
        q = knowledge.get_question("bjt_basics", sess["stage"], sess["q_index"])
        tutor.answer(sid, _payload_for(q, True))
    cards = storage.list_review_cards("stu")
    assert len(cards) == 1 and cards[0]["concept_id"] == "bjt_basics"
    assert cards[0]["card"]["outcome"] == "easy"  # clean run: no hints used
    assert cards[0]["due"] > time.time()
