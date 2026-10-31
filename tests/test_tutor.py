"""End-to-end checks of the V0.3 teaching engine (no server, no LLM key)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import knowledge, storage, tutor  # noqa: E402

storage.DB_PATH = Path(__file__).resolve().parent / "test.db"
if storage.DB_PATH.exists():
    storage.DB_PATH.unlink()
storage.init_db()


def payload_for(concept_id, stage, index, correct=True):
    q = knowledge.get_question(concept_id, stage, index)
    qtype = q.get("type", "mcq")
    if qtype == "mcq":
        target = next(i for i, o in enumerate(q["options"]) if bool(o.get("correct")) == correct)
        return {"option_index": target}
    if qtype == "numeric":
        return {"value": q["answer"] if correct else q["answer"] + 10 * q["tolerance"] + 1}
    # explain
    if correct:
        text = " ".join(g[0] for g in q["rubric_groups"]) + " " + q["model_answer"]
        return {"text": text}
    return {"text": "不知道"}


def play_concept(student, concept_id, correct=True):
    """Walk a whole concept; return the final answer result."""
    s = tutor.start_session(student, concept_id)
    sid = s["session"]["id"]
    stage, idx = "diagnose", 0
    last = None
    for _ in range(30):
        last = tutor.answer(sid, payload_for(concept_id, stage, idx, correct))
        if "question" not in last:
            return last
        if last["next_stage"] != stage:
            stage, idx = last["next_stage"], 0
        elif last["action"] == "next_in_stage":
            idx += 1
        # retry_with_demo: same stage/index again; answering correctly proceeds
    raise AssertionError("flow did not terminate")


def test_full_concept_masters():
    r = play_concept("t1", "bjt_basics")
    assert r["mastery"] == "mastered", r
    assert storage.get_progress("t1")["bjt_basics"]["status"] == "mastered"


def test_all_concepts_completable():
    for c in knowledge.list_concepts():
        r = play_concept("t_all", c["id"])
        assert r["mastery"] in ("mastered", "passed_with_help"), (c["id"], r)


def test_wrong_test_gives_needs_review_and_profile_recommends_it():
    s = tutor.start_session("t2", "amp_metrics")
    sid = s["session"]["id"]
    tutor.answer(sid, payload_for("amp_metrics", "diagnose", 0, True))
    # guided pool: answer all correctly
    for i in range(knowledge.stage_size("amp_metrics", "guided")):
        r = tutor.answer(sid, payload_for("amp_metrics", "guided", i, True))
    assert r["next_stage"] == "test"
    r = tutor.answer(sid, payload_for("amp_metrics", "test", 0, False))
    assert r["mastery"] == "needs_review"
    prof = tutor.profile("t2")
    assert prof["recommendation"]["concept_id"] == "amp_metrics"


def test_numeric_question_judged_by_tolerance():
    s = tutor.start_session("t3", "micro_model")
    sid = s["session"]["id"]
    tutor.answer(sid, payload_for("micro_model", "diagnose", 0, True))
    r = tutor.answer(sid, payload_for("micro_model", "guided", 0, True))
    # guided index 1 is the numeric rbe question (850 ± 20)
    q = knowledge.get_question("micro_model", "guided", 1)
    assert q["type"] == "numeric"
    r = tutor.answer(sid, {"value": 9999})
    assert r["correct"] is False


def test_explain_fallback_judgement():
    s = tutor.start_session("t4", "q_point")
    sid = s["session"]["id"]
    tutor.answer(sid, payload_for("q_point", "diagnose", 0, True))
    tutor.answer(sid, payload_for("q_point", "guided", 0, True))
    tutor.answer(sid, payload_for("q_point", "guided", 1, True))
    # guided index 2 is the explain question
    q = knowledge.get_question("q_point", "guided", 2)
    assert q["type"] == "explain"
    r = tutor.answer(sid, {"text": "因为热了就变了"})
    assert r["correct"] is False  # misses the causal chain; retry allowed
    r = tutor.answer(sid, payload_for("q_point", "guided", 2, True))
    assert r["correct"] is True


def test_hints_blocked_in_test_stage():
    s = tutor.start_session("t5", "cc_cb")
    sid = s["session"]["id"]
    stage, idx = "diagnose", 0
    for _ in range(20):
        sess = storage.get_session(sid)
        if sess["stage"] == "test":
            break
        r = tutor.answer(sid, payload_for("cc_cb", sess["stage"], sess["q_index"], True))
    else:
        raise AssertionError("never reached test stage")
    try:
        tutor.request_hint(sid)
        raise AssertionError("hint should be blocked in test stage")
    except ValueError:
        pass


def test_offline_teacher_chat_answers_with_guidance():
    out = tutor.teacher_chat("t6", "为什么 Re 能稳定静态工作点？")
    assert out["mode"] == "offline"  # no LLM key in test env
    assert "静态工作点" in out["reply"] or "Re" in out["reply"]
    history = storage.recent_chat("t6")
    assert len(history) == 2
