"""Optional LLM layer.

Teaching *decisions* never depend on the LLM — they are made by the
rule-based state machine in tutor.py so they stay explainable and testable.
When LLM_API_KEY is configured (any OpenAI-compatible endpoint, e.g.
DeepSeek), the LLM only rephrases the tutor's feedback more naturally.
Without a key the app runs fully offline with template feedback.
"""
from __future__ import annotations

import json
import os
import urllib.request

API_KEY = os.environ.get("LLM_API_KEY", "")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")


def enabled() -> bool:
    return bool(API_KEY)


def polish_feedback(system_hint: str, draft: str) -> str:
    """Return an LLM-polished version of draft, or draft itself on any failure."""
    if not enabled():
        return draft
    try:
        body = json.dumps(
            {
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是一位耐心的模拟电子技术老师。用口语化中文把给学生的反馈"
                            "改写得更亲切、更清楚，但不得改变其中的教学结论、数字和"
                            "下一步要求，不得直接给出当前题目的答案。控制在120字内。"
                            f"背景：{system_hint}"
                        ),
                    },
                    {"role": "user", "content": draft},
                ],
                "temperature": 0.4,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE_URL}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        return text or draft
    except Exception:
        return draft
