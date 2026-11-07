"""Evaluation harness for the guided learning agent.

Two layers, both runnable offline:

  A. Teaching cases (evals/teaching_cases.json)
     Scripted student personas are replayed through the real tutor engine
     against a throwaway database; each case asserts the teaching decision
     the engine must produce (mastery verdict, misconception attribution,
     overconfidence flag, hint refusal in the test stage). Deterministic —
     this is what CI runs (via tests/test_evals.py).

  B. Judge agreement (evals/golden_explanations.json)
     Human-labelled open answers are scored by the explain judge; we report
     agreement with the human labels. Two judge modes:
       offline — the keyword-group fallback built into tutor._judge
       llm     — the configured LLM judge (needs LLM_API_KEY; skipped otherwise)
     Disagreements are listed case by case: they are the harness's real
     output, showing exactly where the judge can be fooled.

Usage:
  python -m evals.run_evals              # A + B(offline) [+ B(llm) if key set]
  python -m evals.run_evals --json out.json
Exit code is non-zero when any teaching case fails.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import knowledge, llm, storage, tutor  # noqa: E402

EVALS_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------- payloads
def _current(session_id: str) -> tuple[dict, dict]:
    session = storage.get_session(session_id)
    q = knowledge.get_question(session["concept_id"], session["stage"], session["q_index"])
    return session, q


def _payload(question: dict, correct: bool, confidence: int | None = None,
             misconception: str | None = None) -> dict:
    qtype = question.get("type", "mcq")
    if qtype == "mcq":
        if misconception:
            idx = next(i for i, o in enumerate(question["options"])
                       if o.get("misconception") == misconception)
        else:
            idx = next(i for i, o in enumerate(question["options"])
                       if bool(o.get("correct")) == correct)
        body: dict = {"option_index": idx}
    elif qtype == "numeric":
        body = {"value": question["answer"] if correct
                else question["answer"] + 10 * question["tolerance"] + 1}
    else:  # explain
        if correct:
            text = " ".join(g[0] for g in question["rubric_groups"]) + " " + question["model_answer"]
        else:
            text = "不知道"
        body = {"text": text}
    if confidence is not None:
        body["confidence"] = confidence
    return body


def _answer_current(sid: str, correct: bool, **kw) -> dict:
    _, q = _current(sid)
    return tutor.answer(sid, _payload(q, correct, **kw))


def _walk(sid: str, decide, limit: int = 60) -> dict:
    """Answer questions until the session completes.

    decide(session, question) -> dict of answer kwargs (correct/confidence/…)
    or the string 'stop'. Returns the last answer result.
    """
    last: dict = {}
    for _ in range(limit):
        session, q = _current(sid)
        if session["status"] != "in_progress":
            break
        choice = decide(session, q)
        if choice == "stop":
            break
        last = tutor.answer(sid, _payload(q, **choice))
        if "question" not in last:
            break
    return last


# ---------------------------------------------------------------- layer A
def _run_case(case: dict) -> tuple[bool, str]:
    student = f"eval-{case['id']}"
    concept = case["concept"]
    style = case["style"]
    start = tutor.start_session(student, concept)
    sid = start["session"]["id"]
    expect = case["expect"]

    if style == "all_correct":
        last = _walk(sid, lambda s, q: {"correct": True})
    elif style == "all_wrong":
        last = _walk(sid, lambda s, q: {"correct": False})
    elif style == "correct_with_hints":
        n = case.get("hints_before_each_answer", 2)

        def decide(s, q):
            if s["stage"] != "test":
                for _ in range(n):
                    tutor.request_hint(sid)
            return {"correct": True}
        last = _walk(sid, decide)
    elif style == "guided_struggle":
        state = {"seen_guided": False, "wrong_left": 0}

        def decide(s, q):
            if s["stage"] == "guided" and not state["seen_guided"]:
                state["seen_guided"] = True
                state["wrong_left"] = 2
            if state["wrong_left"] > 0:
                state["wrong_left"] -= 1
                return {"correct": False}
            return {"correct": True}
        last = _walk(sid, decide)
    elif style == "review_queue":
        _walk(sid, lambda s, q: {"correct": True})
        from app import review as _review

        card = storage.get_review_card(student, concept)
        if card is None:
            return False, "no review card was created after completing the concept"
        import time as _time

        storage.set_review_card(student, concept, card["card"], _time.time() - 60)
        due = _review.due_reviews(student)
        ok = any(d["concept_id"] == concept for d in due)
        return ok, f"expected {concept} in due queue, got {[d['concept_id'] for d in due]}"
    elif style == "first_wrong_misconception":
        _, q = _current(sid)
        code = next(o["misconception"] for o in q["options"] if o.get("misconception"))
        tutor.answer(sid, _payload(q, False, misconception=code))
        prof = tutor.profile(student)
        codes = [m["code"] for m in prof["misconceptions"]]
        ok = code in codes
        return ok, f"expected misconception {code} in profile, got {codes}"
    elif style == "first_confident_wrong":
        res = _answer_current(sid, False, confidence=5)
        ok = bool(res.get("calibration"))
        return ok, f"expected calibration flag, got {res.get('calibration')!r}"
    elif style == "hint_in_test":
        def decide(s, q):
            if s["stage"] == "test":
                return "stop"
            return {"correct": True}
        _walk(sid, decide)
        try:
            tutor.request_hint(sid)
        except ValueError:
            return True, "hint refused in test stage"
        return False, "hint was NOT refused in test stage"
    else:
        return False, f"unknown style {style}"

    got = last.get("mastery")
    ok = got == expect.get("mastery")
    return ok, f"expected mastery={expect.get('mastery')}, got {got}"


def run_teaching_cases(db_path: Path | None = None) -> dict:
    """Run layer A against a throwaway DB. Returns a results dict."""
    if db_path is None:
        db_path = Path(tempfile.mkdtemp()) / "evals.db"
    storage.DB_PATH = db_path
    if db_path.exists():
        db_path.unlink()
    storage.init_db()
    cases = json.loads((EVALS_DIR / "teaching_cases.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        try:
            ok, detail = _run_case(case)
        except Exception as exc:  # a crashing case is a failing case
            ok, detail = False, f"exception: {exc!r}"
        results.append({"id": case["id"], "passed": ok, "detail": detail})
    passed = sum(1 for r in results if r["passed"])
    return {"total": len(results), "passed": passed, "cases": results}


# ---------------------------------------------------------------- layer B
def run_judge_cases(mode: str) -> dict | None:
    """Run layer B. mode='offline' forces the keyword judge; mode='llm' uses
    the configured LLM judge (returns None when no key is configured)."""
    if mode == "llm" and not llm.enabled():
        return None
    cases = json.loads((EVALS_DIR / "golden_explanations.json").read_text(encoding="utf-8"))
    original = llm.judge_explain
    if mode == "offline":
        llm.judge_explain = lambda *a, **k: None  # noqa: E731 — force fallback
    rows = []
    try:
        for case in cases:
            concept_id, qid = case["question_ref"].split("/")
            question = next(q for stage in ("diagnose", "guided", "test")
                            for q in knowledge.get_concept(concept_id)["questions"][stage]
                            if q["id"] == qid)
            got, _, _ = tutor._judge(question, {"text": case["answer"]})
            rows.append({"id": case["id"], "category": case["category"],
                         "expected": case["expected_passed"], "got": got,
                         "agree": got == case["expected_passed"]})
    finally:
        llm.judge_explain = original
    agree = sum(1 for r in rows if r["agree"])
    return {"mode": mode, "total": len(rows), "agree": agree,
            "agreement": round(agree / len(rows), 3) if rows else None,
            "cases": rows}


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Guided learning agent eval harness")
    ap.add_argument("--json", type=Path, default=EVALS_DIR / "report.json",
                    help="where to write the machine-readable report")
    args = ap.parse_args()

    teaching = run_teaching_cases()
    judge_offline = run_judge_cases("offline")
    judge_llm = run_judge_cases("llm")

    report = {"teaching": teaching, "judge_offline": judge_offline, "judge_llm": judge_llm}
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[A] teaching cases: {teaching['passed']}/{teaching['total']} passed")
    for r in teaching["cases"]:
        if not r["passed"]:
            print(f"    FAIL {r['id']}: {r['detail']}")
    if judge_offline:
        print(f"[B] judge agreement (offline keyword judge): "
              f"{judge_offline['agree']}/{judge_offline['total']} = {judge_offline['agreement']}")
        for r in judge_offline["cases"]:
            if not r["agree"]:
                print(f"    DISAGREE {r['id']} ({r['category']}): expected {r['expected']}, got {r['got']}")
    if judge_llm:
        print(f"[B] judge agreement (LLM judge): "
              f"{judge_llm['agree']}/{judge_llm['total']} = {judge_llm['agreement']}")
        for r in judge_llm["cases"]:
            if not r["agree"]:
                print(f"    DISAGREE {r['id']} ({r['category']}): expected {r['expected']}, got {r['got']}")
    else:
        print("[B] judge agreement (LLM judge): skipped — no LLM_API_KEY configured")
    print(f"report written to {args.json}")
    return 0 if teaching["passed"] == teaching["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
