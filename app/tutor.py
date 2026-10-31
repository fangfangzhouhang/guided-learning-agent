"""Teaching decision engine (Group A owns this module).

Explainable state machine over question *pools* per stage:

    diagnose (1题) ──► guided (多题, 可用提示) ──► test (多题, 无提示) ──► done

Question types: mcq (选项绑定误区编码) / numeric (数值容差判分) /
explain (开放题: LLM 按要点判读, 离线时用关键词组规则兜底).

Mastery is evidence-based: all test questions correct AND hints <= 1
AND no guided question failed twice. Anything less is recorded honestly
as passed_with_help or needs_review — never from the student saying
"I understand".
"""
from __future__ import annotations

from . import knowledge, llm, storage

MAX_HINTS_FOR_MASTERY = 1


# ---------- session flow ----------

def start_session(student: str, concept_id: str) -> dict:
    concept = knowledge.get_concept(concept_id)
    if not concept:
        raise ValueError(f"unknown concept: {concept_id}")
    session = storage.create_session(student, concept_id)
    question = knowledge.get_question(concept_id, "diagnose", 0)
    return {
        "session": session,
        "message": (
            f"我们来学「{concept['title']}」。先不急着讲，我先问你一个问题，"
            "看看你现在的理解到哪一步了——答错完全没关系，这一步就是用来定位问题的。"
        ),
        "question": knowledge.public_question(question),
        "stage": "diagnose",
    }


def _current_question(session: dict) -> dict:
    q = knowledge.get_question(session["concept_id"], session["stage"], session["q_index"])
    if q is None:
        raise ValueError("no question at current position")
    return q


def request_hint(session_id: str) -> dict:
    session = storage.get_session(session_id)
    if not session or session["status"] != "in_progress":
        raise ValueError("session not active")
    if session["stage"] == "test":
        raise ValueError("独立测验阶段不能使用提示——这一步就是要验证你能不能独立完成")
    question = _current_question(session)
    hints_used = session["hints_used"]
    storage.record_event(session_id, "hint_requested", {"stage": session["stage"], "count": hints_used + 1})
    storage.update_session(session_id, hints_used=hints_used + 1)
    if hints_used % 2 == 0:
        return {"hint_level": 1, "hint": question["hint1"], "demonstration": None}
    return {"hint_level": 2, "hint": question.get("hint2", question["hint1"]),
            "demonstration": question.get("demonstration")}


def _judge(question: dict, payload: dict) -> tuple[bool, str | None, str]:
    """Return (correct, misconception_code, feedback_extra)."""
    qtype = question.get("type", "mcq")
    if qtype == "mcq":
        idx = payload.get("option_index")
        if idx is None or idx < 0 or idx >= len(question["options"]):
            raise ValueError("option_index out of range")
        chosen = question["options"][idx]
        return bool(chosen.get("correct")), chosen.get("misconception"), ""
    if qtype == "numeric":
        value = payload.get("value")
        if value is None:
            raise ValueError("value required for numeric question")
        ok = abs(float(value) - float(question["answer"])) <= float(question["tolerance"])
        return ok, None if ok else question.get("wrong_misconception"), ""
    # explain: LLM first, keyword-group rubric as offline fallback
    text = (payload.get("text") or "").strip()
    if not text:
        raise ValueError("text required for explain question")
    verdict = llm.judge_explain(question["prompt"], question["model_answer"], text)
    if verdict is not None:
        return verdict["passed"], None if verdict["passed"] else "explain_incomplete", verdict["feedback"]
    groups = question["rubric_groups"]
    hit = sum(1 for g in groups if any(k in text for k in g))
    passed = hit >= max(1, len(groups) - 1)
    missing = [g[0] for g in groups if not any(k in text for k in g)]
    extra = "你提到了大部分关键点。" if passed else f"还缺关键环节，想想：{'、'.join(missing)} 在链条里起什么作用？"
    return passed, None if passed else "explain_incomplete", extra


def answer(session_id: str, payload: dict) -> dict:
    session = storage.get_session(session_id)
    if not session or session["status"] != "in_progress":
        raise ValueError("session not active")
    concept_id = session["concept_id"]
    stage = session["stage"]
    q_index = session["q_index"]
    question = _current_question(session)
    confidence = payload.get("confidence")

    correct, misconception, extra = _judge(question, payload)
    storage.record_event(
        session_id, "answer",
        {"stage": stage, "question_id": question["id"], "correct": correct,
         "misconception": misconception, "confidence": confidence},
    )
    concept = knowledge.get_concept(concept_id)
    result: dict = {
        "correct": correct,
        "misconception": misconception,
        "explanation": question["explanation"],
        "calibration": _calibration(confidence, correct),
    }
    if extra:
        result["judge_feedback"] = extra
    if misconception and misconception in concept["misconceptions"]:
        result["misconception_text"] = concept["misconceptions"][misconception]

    pool_size = knowledge.stage_size(concept_id, stage)
    has_next_in_stage = q_index + 1 < pool_size

    if stage == "diagnose":
        if correct:
            draft = "诊断通过，说明你对这个知识点已经有基础了。进入引导练习，换几种问法继续。"
        else:
            reason = result.get("misconception_text", "对这个概念还不熟悉")
            draft = f"这道题答错了，而且错得很有信息量：你的思路里{reason}。先看一个完整的示范，想清楚每一步，再来做引导练习。"
            result["demonstration"] = question.get("demonstration")
        result["action"] = "advance"
        result["next_stage"] = "guided"
        storage.update_session(session_id, stage="guided", q_index=0)
        result["question"] = knowledge.public_question(knowledge.get_question(concept_id, "guided", 0))
    elif stage == "guided":
        if correct:
            if has_next_in_stage:
                draft = "这道对了，引导练习继续，下一题换个角度。"
                result["action"] = "next_in_stage"
                result["next_stage"] = "guided"
                storage.update_session(session_id, q_index=q_index + 1)
                result["question"] = knowledge.public_question(
                    knowledge.get_question(concept_id, "guided", q_index + 1))
            else:
                draft = ("引导练习全部完成。最后一步是独立测验：没有提示，"
                         "做对了才说明你是真的掌握了，而不是跟着提示走。")
                result["action"] = "advance"
                result["next_stage"] = "test"
                storage.update_session(session_id, stage="test", q_index=0)
                result["question"] = knowledge.public_question(
                    knowledge.get_question(concept_id, "test", 0))
        else:
            attempts_key = f"retry_{question['id']}"
            events = storage.list_events(session_id)
            retries = sum(1 for e in events if e["kind"] == "answer"
                          and e["payload"].get("question_id") == question["id"]
                          and not e["payload"].get("correct"))
            if retries <= 1:
                reason = result.get("misconception_text", "这个点还没想通")
                draft = f"还差一点：问题出在{reason}。看完示范后请重新做一次这道题。"
                result["action"] = "retry_with_demo"
                result["demonstration"] = question.get("demonstration")
                result["next_stage"] = "guided"
                result["question"] = knowledge.public_question(question)
            else:
                storage.update_session(session_id, weak=1)
                if has_next_in_stage:
                    draft = "这道题先放一放，已经记下这是你的薄弱点，后面复习会再遇到它。先继续下一题。"
                    result["action"] = "next_in_stage"
                    result["next_stage"] = "guided"
                    storage.update_session(session_id, q_index=q_index + 1)
                    result["question"] = knowledge.public_question(
                        knowledge.get_question(concept_id, "guided", q_index + 1))
                else:
                    draft = "引导练习结束（有一道题还没攻克，已记为薄弱点）。接下来是独立测验，凭现在的理解认真做。"
                    result["action"] = "advance"
                    result["next_stage"] = "test"
                    storage.update_session(session_id, stage="test", q_index=0)
                    result["question"] = knowledge.public_question(
                        knowledge.get_question(concept_id, "test", 0))
    else:  # test stage: no retries, collect evidence
        events = storage.list_events(session_id)
        test_answers = [e["payload"] for e in events
                        if e["kind"] == "answer" and e["payload"].get("stage") == "test"]
        if has_next_in_stage:
            draft = "已记录，继续下一道测验题。"
            result["action"] = "next_in_stage"
            result["next_stage"] = "test"
            storage.update_session(session_id, q_index=q_index + 1)
            result["question"] = knowledge.public_question(
                knowledge.get_question(concept_id, "test", q_index + 1))
        else:
            all_correct = all(a.get("correct") for a in test_answers)
            storage.update_session(session_id, status="completed")
            fresh = storage.get_session(session_id)
            if all_correct and fresh["hints_used"] <= MAX_HINTS_FOR_MASTERY and not fresh["weak"]:
                status, action = "mastered", "mastered"
                draft = "独立测验全部通过，而且基本没有依赖提示——这个知识点算真正掌握了。去知识地图看看下一个吧。"
            elif all_correct:
                status, action = "passed_with_help", "passed_with_help"
                draft = "测验答对了，但过程中用了较多提示或有薄弱题，先记为「帮助下通过」。过段时间不看提示再自测一次，答对才算扎实。"
            else:
                status, action = "needs_review", "needs_review"
                draft = "独立测验没有全对，没关系——已经把卡点记进你的画像了，复习时会优先推这个知识点。学习记录不会假装你已经掌握。"
            storage.set_mastery(session["student"], concept_id, status,
                                {"test_all_correct": all_correct,
                                 "hints_used": fresh["hints_used"], "weak": bool(fresh["weak"])})
            result["action"] = action
            result["mastery"] = status

    result["feedback"] = draft
    result["session"] = storage.get_session(session_id)
    return result


def _calibration(confidence, correct: bool) -> str | None:
    if confidence is None:
        return None
    if confidence >= 4 and not correct:
        return "你答题前很有信心但答错了——这正是「感觉懂了」的错觉，下次遇到这种题要多留个心眼。"
    if confidence <= 2 and correct:
        return "你其实已经答对了，但信心不足。多做两道变式题，这种感觉会慢慢变准。"
    return None


# ---------- learner profile ----------

def profile(student: str) -> dict:
    mastery = storage.get_progress(student)
    counts = storage.misconception_counts(student)
    texts: dict[str, str] = {}
    for c in knowledge.list_concepts():
        full = knowledge.get_concept(c["id"])
        for code, text in full["misconceptions"].items():
            texts[code] = text
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
    recommendation = None
    for c in knowledge.list_concepts():
        if mastery.get(c["id"], {}).get("status") == "needs_review":
            recommendation = {"concept_id": c["id"], "reason": f"「{c['title']}」上次测验没通过，先复习它"}
            break
    if recommendation is None:
        for c in knowledge.list_concepts():
            if c["id"] not in mastery:
                recommendation = {"concept_id": c["id"], "reason": f"下一个新知识点：「{c['title']}」"}
                break
    if recommendation is None:
        recommendation = {"concept_id": None, "reason": "这一章都学过了，可以开始间隔复习或挑战自由提问"}
    return {
        "student": student,
        "mastery": mastery,
        "misconceptions": [{"code": code, "count": n, "text": texts.get(code, code)} for code, n in top],
        "recommendation": recommendation,
    }


# ---------- patient teacher chat ----------

def _teacher_system_prompt(student: str) -> str:
    prof = profile(student)
    digest = "\n".join(
        f"- {c['title']}：{c['summary']} 要点：{'；'.join(c['key_points'])}"
        for c in knowledge.list_concepts()
    )
    mastery_text = "、".join(
        f"{knowledge.get_concept(cid)['title']}={m['status']}" for cid, m in prof["mastery"].items()
    ) or "暂无记录"
    misc_text = "、".join(f"{m['text']}(出现{m['count']}次)" for m in prof["misconceptions"]) or "暂无"
    return (
        "你是一位极有耐心、懂学生的现电（模拟电子技术）老师，正在辅导一名大学生学习三极管放大电路。\n"
        "教学守则：\n"
        "1. 一步步引导：先问一个小问题定位理解，再给提示，最后才示范；不要一上来整段灌输，也不要直接甩最终答案。"
        "学生连续两次表示不懂或答错时，给一个完整示范再请他复述关键一步。\n"
        "2. 语气亲切、具体，多鼓励；指出错误时说清错在哪个概念上，不说教。\n"
        "3. 只围绕本课内容回答；学生问无关问题时礼貌带回。公式和数值必须准确，不确定就明说。\n"
        "4. 每次回复控制在200字左右，最后留一个小问题或下一步建议。\n"
        f"本课知识摘要：\n{digest}\n"
        f"这个学生的学习画像——已学记录：{mastery_text}；反复出现的误区：{misc_text}。"
        "如果他的问题涉及他的误区，要有意识地多追问一步。"
    )


def teacher_chat(student: str, message: str) -> dict:
    storage.add_chat_message(student, "user", message)
    history = storage.recent_chat(student, limit=10)
    reply = llm.teacher_chat(_teacher_system_prompt(student), history)
    if reply is None:
        reply = _offline_teacher_reply(message)
        mode = "offline"
    else:
        mode = "llm"
    storage.add_chat_message(student, "assistant", reply)
    return {"reply": reply, "mode": mode}


def _offline_teacher_reply(message: str) -> str:
    """Keyword-grounded fallback when no LLM key/network: still guides, never fakes."""
    best, best_hits = None, 0
    for c in knowledge.list_concepts():
        hits = sum(1 for kw in [c["title"], *c["key_points"]] if any(ch in message for ch in kw[:4]))
        hits += sum(1 for word in ["放大", "静态", "工作点", "失真", "rbe", "等效", "负载", "输入电阻", "输出电阻", "射极", "共基", "共集", "通频带"] if word in message and word in c["summary"] + c["title"])
        if hits > best_hits:
            best, best_hits = c, hits
    if best:
        return (
            f"（离线模式）你问的应该和「{best['title']}」有关。先给你一个抓手：{best['summary']}"
            f"要点是：{'；'.join(best['key_points'])}。"
            "你先想一步：你卡住的是概念本身，还是计算时哪一步？把你的思路写给我，我陪你一步步推。"
            f"也可以直接在课程学习里开始「{best['title']}」，我会用题目带你过一遍。"
        )
    return (
        "（离线模式）我现在没连上大模型，没法展开讲，但课程学习里的每个知识点我都备好了诊断、提示和示范。"
        "你可以先告诉我你卡在哪个知识点，或者直接开始一节课，我们一步步来。"
    )
