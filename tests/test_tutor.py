"""End-to-end checks of the teaching state machine (no server needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import storage, tutor  # noqa: E402

storage.DB_PATH = Path(__file__).resolve().parent / "test.db"
if storage.DB_PATH.exists():
    storage.DB_PATH.unlink()
storage.init_db()


def correct_index(concept_id, stage):
    from app import knowledge

    q = knowledge.get_question(concept_id, stage)
    return next(i for i, o in enumerate(q["options"]) if o.get("correct"))


def wrong_index(concept_id, stage):
    from app import knowledge

    q = knowledge.get_question(concept_id, stage)
    return next(i for i, o in enumerate(q["options"]) if not o.get("correct"))


def test_happy_path_masters_concept():
    s = tutor.start_session("tester", "bjt_basics")
    sid = s["session"]["id"]
    r = tutor.answer(sid, correct_index("bjt_basics", "diagnose"))
    assert r["action"] == "advance" and r["next_stage"] == "guided"
    r = tutor.answer(sid, correct_index("bjt_basics", "guided"))
    assert r["next_stage"] == "test"
    r = tutor.answer(sid, correct_index("bjt_basics", "test"))
    assert r["mastery"] == "mastered"
    assert storage.get_progress("tester")["bjt_basics"]["status"] == "mastered"


def test_wrong_diagnosis_triggers_demonstration_and_misconception():
    s = tutor.start_session("tester2", "q_point")
    sid = s["session"]["id"]
    r = tutor.answer(sid, wrong_index("q_point", "diagnose"))
    assert r["action"] == "demonstrate"
    assert r["misconception"] is not None
    assert r["demonstration"]
    r = tutor.answer(sid, correct_index("q_point", "guided"))
    r = tutor.answer(sid, wrong_index("q_point", "test"))
    assert r["mastery"] == "needs_review"


def test_hints_blocked_during_independent_test():
    s = tutor.start_session("tester3", "micro_model")
    sid = s["session"]["id"]
    tutor.answer(sid, correct_index("micro_model", "diagnose"))
    tutor.answer(sid, correct_index("micro_model", "guided"))
    try:
        tutor.request_hint(sid)
        raise AssertionError("hint should be blocked in test stage")
    except ValueError:
        pass


def test_many_hints_downgrade_mastery():
    s = tutor.start_session("tester4", "ce_amp")
    sid = s["session"]["id"]
    tutor.request_hint(sid)
    tutor.request_hint(sid)
    tutor.answer(sid, correct_index("ce_amp", "diagnose"))
    tutor.answer(sid, correct_index("ce_amp", "guided"))
    r = tutor.answer(sid, correct_index("ce_amp", "test"))
    assert r["mastery"] == "passed_with_help"
