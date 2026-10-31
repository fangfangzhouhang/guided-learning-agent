"""Teaching decision engine (Group A owns this module).

A small, explainable state machine. Per concept the flow is:

    diagnose ──correct──► guided ──► test ──► done
        │                     ▲          │
        └──wrong──► hint/demo─┘          └─wrong─► needs_review

Principles (from the project brief):
- Never judge mastery from the student saying "I understand".
  Mastery requires passing the independent variant test (stage=test)
  with at most MAX_HINTS_FOR_MASTERY hints in the whole session.
- Diagnose *why* an answer is wrong: every wrong option in the question
  bank is tagged with a misconception code, so feedback can target the
  root cause instead of just saying "wrong, try again".
- Beginners get a worked demonstration; students with a specific
  misconception get a targeted hint first. Hints are layered (2 levels).
"""
from __future__ import annotations

from . import knowledge, llm, storage

MAX_HINTS_FOR_MASTERY = 1
STAGE_ORDER = ["diagnose", "guided", "test"]


def start_session(student: str, concept_id: str) -> dict:
    concept = knowledge.get_concept(concept_id)
    if not concept:
        raise ValueError(f"unknown concept: {concept_id}")
    session = storage.create_session(student, concept_id)
    question = knowledge.get_question(concept_id, "diagnose")
    return {
        "session": session,
        "message": (
            f"我们来学「{concept['title']}」。先不急着讲，我先问你一个问题，"
            "看看你现在的理解到哪一步了——答错完全没关系，这一步就是用来定位问题的。"
        ),
        "question": knowledge.public_question(question),
        "stage": "diagnose",
    }


def request_hint(session_id: str) -> dict:
    session = storage.get_session(session_id)
    if not session or session["status"] != "in_progress":
        raise ValueError("session not active")
    stage = session["stage"]
    if stage == "test":
        raise ValueError("独立测验阶段不能使用提示——这一步就是要验证你能不能独立完成")
    question = knowledge.get_question(session["concept_id"], stage)
    hints_used = session["hints_used"]
    storage.record_event(session_id, "hint_requested", {"stage": stage, "count": hints_used + 1})
    storage.update_session(session_id, hints_used=hints_used + 1)
    if hints_used == 0:
        return {"hint_level": 1, "hint": question["hint1"], "demonstration": None}
    # Second request escalates to a full worked demonstration.
    return {"hint_level": 2, "hint": question["hint2"], "demonstration": question["demonstration"]}


def answer(session_id: str, option_index: int, confidence: int | None = None) -> dict:
    session = storage.get_session(session_id)
    if not session or session["status"] != "in_progress":
        raise ValueError("session not active")
    concept_id = session["concept_id"]
    stage = session["stage"]
    question = knowledge.get_question(concept_id, stage)
    if option_index < 0 or option_index >= len(question["options"]):
        raise ValueError("option_index out of range")
    chosen = question["options"][option_index]
    correct = bool(chosen.get("correct"))
    misconception = chosen.get("misconception")

    storage.record_event(
        session_id,
        "answer",
        {
            "stage": stage,
            "question_id": question["id"],
            "correct": correct,
            "misconception": misconception,
            "confidence": confidence,
        },
    )

    concept = knowledge.get_concept(concept_id)
    result: dict = {
        "correct": correct,
        "misconception": misconception,
        "explanation": question["explanation"],
        "calibration": _calibration(confidence, correct),
    }

    if stage == "diagnose":
        if correct:
            draft = (
                "诊断通过，说明你对这个知识点已经有基础了。直接进入引导练习，"
                "看看换个问法你还会不会。"
            )
            result["action"] = "advance"
            result["next_stage"] = "guided"
            storage.update_session(session_id, stage="guided")
            result["question"] = knowledge.public_question(
                knowledge.get_question(concept_id, "guided")
            )
        else:
            reason = concept["misconceptions"].get(misconception, "对这个概念还不熟悉")
            draft = (
                f"这道题答错了，而且错得很有信息量：你的思路里{reason}。"
                "先看一个完整的示范，想清楚每一步，再来做引导练习。"
            )
            result["action"] = "demonstrate"
            result["demonstration"] = question["demonstration"]
            result["next_stage"] = "guided"
            storage.update_session(session_id, stage="guided")
            result["question"] = knowledge.public_question(
                knowledge.get_question(concept_id, "guided")
            )
    elif stage == "guided":
        if correct:
            draft = (
                "引导练习通过。最后一步是独立测验：这道题没有提示，"
                "做对了才说明你是真的掌握了，而不是跟着提示走。"
            )
            result["action"] = "advance"
            result["next_stage"] = "test"
            storage.update_session(session_id, stage="test")
            result["question"] = knowledge.public_question(
                knowledge.get_question(concept_id, "test")
            )
        else:
            reason = concept["misconceptions"].get(misconception, "这个点还没想通")
            draft = (
                f"还差一点：问题出在{reason}。看完示范后请重新选一次这道题。"
            )
            result["action"] = "retry_with_demo"
            result["demonstration"] = question["demonstration"]
            result["next_stage"] = "guided"
            result["question"] = knowledge.public_question(question)
    else:  # stage == test, the independent check
        storage.update_session(session_id, status="completed")
        if correct and session["hints_used"] <= MAX_HINTS_FOR_MASTERY:
            storage.set_mastery(
                session["student"],
                concept_id,
                "mastered",
                {"test_correct": True, "hints_used": session["hints_used"]},
            )
            draft = (
                "独立测验通过，而且这次基本没有依赖提示——这个知识点算真正掌握了。"
                "去知识地图看看下一个知识点吧。"
            )
            result["action"] = "mastered"
            result["mastery"] = "mastered"
        elif correct:
            storage.set_mastery(
                session["student"],
                concept_id,
                "passed_with_help",
                {"test_correct": True, "hints_used": session["hints_used"]},
            )
            draft = (
                "独立测验答对了，但这节你用了比较多的提示，先记为「在帮助下通过」。"
                "过一会儿建议不看提示再自测一次，答对才算扎实。"
            )
            result["action"] = "passed_with_help"
            result["mastery"] = "passed_with_help"
        else:
            storage.set_mastery(
                session["student"],
                concept_id,
                "needs_review",
                {"test_correct": False, "misconception": misconception},
            )
            reason = concept["misconceptions"].get(misconception, "这个点还没掌握")
            draft = (
                f"独立测验没通过，卡点还是：{reason}。没关系，我把这一节的示范再放一次，"
                "看完可以重新开始这一节。学习记录已经保存，不会假装你已经掌握了。"
            )
            result["action"] = "needs_review"
            result["mastery"] = "needs_review"
            result["demonstration"] = question.get("demonstration")

    result["feedback"] = llm.polish_feedback(
        f"知识点：{concept['title']}；阶段：{stage}；动作：{result['action']}", draft
    )
    result["session"] = storage.get_session(session_id)
    return result


def _calibration(confidence: int | None, correct: bool) -> str | None:
    """Metacognitive calibration: compare self-rated confidence with reality."""
    if confidence is None:
        return None
    if confidence >= 4 and not correct:
        return "你答题前很有信心但答错了——这正是「感觉懂了」的错觉，下次遇到这种题要多留个心眼。"
    if confidence <= 2 and correct:
        return "你其实已经答对了，但信心不足。多做两道变式题，这种感觉会慢慢变准。"
    return None
