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


def judge_explain(prompt: str, model_answer: str, student_text: str) -> dict | None:
    """Judge an open answer. Returns {passed, feedback} or None if LLM unavailable."""
    out = _chat(
        [
            {
                "role": "system",
                "content": (
                    "你是现电课程的阅卷老师。判断学生的开放题回答是否抓住了关键因果链。"
                    "只输出 JSON：{\"passed\": true/false, \"feedback\": \"不超过80字的中文点评，"
                    "指出答对了什么、缺了什么，不要直接抄标准答案\"}。不要输出其他内容。"
                ),
            },
            {
                "role": "user",
                "content": f"题目：{prompt}\n参考答案要点：{model_answer}\n学生回答：{student_text}",
            },
        ],
        temperature=0.1,
    )
    if not out:
        return None
    try:
        start, end = out.index("{"), out.rindex("}") + 1
        verdict = json.loads(out[start:end])
        return {"passed": bool(verdict["passed"]), "feedback": str(verdict["feedback"])}
    except Exception:
        return None


def teacher_chat(system_prompt: str, history: list[dict]) -> str | None:
    """Free-form patient-teacher chat. history includes the new user message."""
    return _chat([{"role": "system", "content": system_prompt}, *history], temperature=0.5, timeout=45)
