"""Elo dual-rating tests: math properties + first-attempt rule + profile."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import elo, knowledge, storage, tutor  # noqa: E402


@pytest.fixture()
def fresh_db(tmp_path):
    old = storage.DB_PATH
    storage.DB_PATH = tmp_path / "elo.db"
    storage.init_db()
    yield
    storage.DB_PATH = old


def _payload_for(q, correct=True):
    if q.get("type", "mcq") == "mcq":
        idx = next(i for i, o in enumerate(q["options"]) if bool(o.get("correct")) == correct)
        return {"option_index": idx}
    if q.get("type") == "numeric":
        return {"value": q["answer"] if correct else q["answer"] + 10 * q["tolerance"] + 1}
    return {"text": " ".join(g[0] for g in q["rubric_groups"]) + " " + q["model_answer"]
            if correct else "不知道"}


def test_even_match_win_gains_half_k(fresh_db):
    r = elo.record_attempt("s1", "c", "q1", True)
    assert r["student_rating"] == 1216.0  # 1200 + 32 * 0.5
    assert r["question_rating"] == 1196.0  # 1200 - 8 * 0.5


def test_beating_a_hard_question_gains_more(fresh_db):
    storage.set_rating("question", "c/qh", 1600.0, 10)
    r = elo.record_attempt("s1", "c", "qh", True)
    assert r["student_rating"] > 1216.0  # upset win pays more than 16


def test_losing_to_an_easy_question_drops_more(fresh_db):
    storage.set_rating("question", "c/qe", 800.0, 10)
    r = elo.record_attempt("s1", "c", "qe", False)
    assert r["student_rating"] < 1184.0  # expected win, lost: bigger drop


def test_first_attempt_only_counts_in_a_session(fresh_db):
    s = tutor.start_session("stu", "bjt_basics")
    sid = s["session"]["id"]
    sess = storage.get_session(sid)
    q0 = knowledge.get_question("bjt_basics", sess["stage"], sess["q_index"])
    r1 = tutor.answer(sid, _payload_for(q0, True))
    assert "elo" in r1 and r1["elo"]["question_attempts"] == 1

    # walk to the first guided question, fail it, then retry after the demo:
    # the retry must NOT count as a second Elo attempt.
    for _ in range(10):
        sess = storage.get_session(sid)
        if sess["stage"] == "guided":
            break
        q = knowledge.get_question("bjt_basics", sess["stage"], sess["q_index"])
        tutor.answer(sid, _payload_for(q, True))
    g = knowledge.get_question("bjt_basics", "guided", sess["q_index"])
    rw = tutor.answer(sid, _payload_for(g, False))
    assert "elo" in rw
    rr = tutor.answer(sid, _payload_for(g, True))  # retry after demonstration
    assert "elo" not in rr
    _, attempts = storage.get_rating("question", f"bjt_basics/{g['id']}")
    assert attempts == 1


def test_profile_exposes_ratings(fresh_db):
    elo.record_attempt("stu", "bjt_basics", "d1", False)
    prof = tutor.profile("stu")
    assert prof["student_rating"] < 1200
    assert prof["hardest_questions"] and \
        prof["hardest_questions"][0]["question"] == "bjt_basics/d1"
