"""Optional LLM layer (DeepSeek / any OpenAI-compatible endpoint).

Teaching *decisions* stay in tutor.py's explainable state machine.
The LLM is used for three bounded jobs:
1. polishing feedback wording,
2. judging open-ended ("explain") answers against a rubric,
3. the free-form patient-teacher chat.
Every job has a deterministic offline fallback, so the app never breaks
without a key or network.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv() -> None:
    """Load project-root .env into the environment (real env vars win).

    Keeps the documented workflow true: copy .env.example to .env, fill in
    LLM_API_KEY, run the app — no shell exports needed. The .env file is
    gitignored and must never be committed.
    """
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

API_KEY = os.environ.get("LLM_API_KEY", "")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")


def enabled() -> bool:
    return bool(API_KEY)


def _chat(messages: list[dict], temperature: float = 0.4, timeout: int = 30) -> str | None:
    if not enabled():
        return None
    try:
        body = json.dumps(
            {"model": MODEL, "messages": messages, "temperature": temperature}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE_URL}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        return text or None
    except Exception:
        return None


def polish_feedback(system_hint: str, draft: str) -> str:
    out = _chat(
        [
            {
                "role": "system",
                "content": (
                    "你是一位耐心的现电（模拟电子技术）老师。用口语化中文把反馈改写得更亲切清楚，"
                    "不得改变教学结论、数字和下一步要求，不得给出当前题目答案。120字内。"
                    f"背景：{system_hint}"
                ),
            },
            {"role": "user", "content": draft},
        ]
    )
    return out or draft


def _judge_once(prompt: str, model_answer: str, student_text: str,
                rubric_groups: list | None) -> dict | None:
    """One structured judging pass (rubric template borrowed from
    Prometheus-Eval's shape, run on our own API model — no local model)."""
    if rubric_groups:
        rubric = "\n".join(
            f"  {i + 1}. {' / '.join(g)}" for i, g in enumerate(rubric_groups))
    else:
        rubric = "  （见参考答案要点）"
    out = _chat(
        [
            {
                "role": "system",
                "content": (
                    "你是现电课程的阅卷老师，按评分标准逐项核对学生的开放题回答。\n"
                    "判定规则（严格执行）：\n"
                    "1. 先看因果链：方向必须正确、链条必须完整。方向反了或链条断裂，"
                    "无论关键词出现多少，一律不通过。\n"
                    "2. 再逐项核对评分标准：说清了才算命中，只蹭到关键词、没有说清"
                    "因果关系的不算命中。\n"
                    "3. 字数多、态度好不加分；堆砌术语凑长度按未说清处理。\n"
                    "4. 关键项全部命中且因果正确才判 passed=true，缺任何关键一环"
                    "即 passed=false。\n"
                    "只输出 JSON：{\"passed\": true/false, \"feedback\": \"不超过80字的"
                    "中文点评，指出说对了什么、缺了或错了什么，不要抄标准答案\"}。"
                    "不要输出其他内容。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"题目：{prompt}\n参考答案要点：{model_answer}\n"
                    f"评分标准（逐项核对）：\n{rubric}\n学生回答：{student_text}"
                ),
            },
        ],
        temperature=0.2,
    )
    if not out:
        return None
    try:
        start, end = out.index("{"), out.rindex("}") + 1
        verdict = json.loads(out[start:end])
        return {"passed": bool(verdict["passed"]), "feedback": str(verdict["feedback"])}
    except Exception:
        return None


def judge_explain(prompt: str, model_answer: str, student_text: str,
                  rubric_groups: list | None = None) -> dict | None:
    """Judge an open answer with self-consistency voting.

    The same answer is judged JUDGE_SAMPLES times (default 3) and the
    majority verdict wins — a single LLM judgement is measurably easy to
    fool with keyword stuffing (see docs/evals.md). Returns
    {passed, feedback, votes} or None if every call failed (the caller
    then falls back to the deterministic keyword judge).
    """
    samples = max(1, int(os.environ.get("JUDGE_SAMPLES", "3")))
    verdicts = [v for v in (_judge_once(prompt, model_answer, student_text, rubric_groups)
                            for _ in range(samples)) if v is not None]
    if not verdicts:
        return None
    passed_votes = sum(1 for v in verdicts if v["passed"])
    passed = passed_votes * 2 > len(verdicts)
    representative = next(v for v in verdicts if v["passed"] == passed)
    return {"passed": passed, "feedback": representative["feedback"],
            "votes": f"{passed_votes}/{len(verdicts)}"}


def teacher_chat(system_prompt: str, history: list[dict]) -> str | None:
    """Free-form patient-teacher chat. history includes the new user message."""
    return _chat([{"role": "system", "content": system_prompt}, *history], temperature=0.5, timeout=45)
