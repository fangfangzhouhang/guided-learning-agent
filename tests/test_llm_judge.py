"""Unit tests for the LLM explain judge: rubric prompt + self-consistency
voting. The network call (_chat) is monkeypatched — no key, no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import llm  # noqa: E402

PASS = '{"passed": true, "feedback": "因果链完整"}'
FAIL = '{"passed": false, "feedback": "缺关键一环"}'


def scripted(responses):
    it = iter(responses)
    captured = []

    def fake_chat(messages, temperature=0.4, timeout=30):
        captured.append(messages)
        return next(it, None)
    return fake_chat, captured


def test_voting_majority_pass(monkeypatch):
    fake, _ = scripted([PASS, FAIL, PASS])
    monkeypatch.setattr(llm, "_chat", fake)
    monkeypatch.setattr(llm, "API_KEY", "test")
    v = llm.judge_explain("题", "要点", "学生答", rubric_groups=[["VE"], ["IB"]])
    assert v["passed"] is True and v["votes"] == "2/3"


def test_voting_majority_fail(monkeypatch):
    fake, _ = scripted([FAIL, PASS, FAIL])
    monkeypatch.setattr(llm, "_chat", fake)
    monkeypatch.setattr(llm, "API_KEY", "test")
    v = llm.judge_explain("题", "要点", "学生答")
    assert v["passed"] is False and v["votes"] == "1/3"


def test_all_calls_fail_returns_none(monkeypatch):
    fake, _ = scripted([None, None, None])
    monkeypatch.setattr(llm, "_chat", fake)
    monkeypatch.setattr(llm, "API_KEY", "test")
    assert llm.judge_explain("题", "要点", "学生答") is None


def test_bad_json_is_ignored(monkeypatch):
    fake, _ = scripted(["not json", PASS, PASS])
    monkeypatch.setattr(llm, "_chat", fake)
    monkeypatch.setattr(llm, "API_KEY", "test")
    v = llm.judge_explain("题", "要点", "学生答")
    assert v["passed"] is True and v["votes"] == "2/2"


def test_rubric_reaches_the_prompt(monkeypatch):
    fake, captured = scripted([PASS, PASS, PASS])
    monkeypatch.setattr(llm, "_chat", fake)
    monkeypatch.setattr(llm, "API_KEY", "test")
    llm.judge_explain("题", "要点", "学生答",
                      rubric_groups=[["VE", "发射极电位"], ["IB", "基极电流"]])
    user_msg = captured[0][1]["content"]
    assert "VE" in user_msg and "基极电流" in user_msg
    system_msg = captured[0][0]["content"]
    assert "关键词" in system_msg  # the anti-keyword-stuffing rule is in force
