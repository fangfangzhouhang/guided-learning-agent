"""Drafting-tool tests: validation gate + never-auto-publish behaviour.
The LLM call is monkeypatched — no key, no network."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("draft_items", ROOT / "tools" / "draft_items.py")
draft_items = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(draft_items)

from app import knowledge, llm  # noqa: E402

GOOD = {
    "type": "mcq", "id": "draft_1", "prompt": "三极管工作在放大区时，发射结与集电结的偏置是？",
    "options": [
        {"text": "发射结正偏、集电结反偏", "correct": True},
        {"text": "发射结正偏、集电结正偏", "misconception": "state_confusion"},
        {"text": "发射结反偏、集电结反偏", "misconception": "state_confusion"},
        {"text": "发射结直接放大电压", "misconception": "voltage_amplifier_myth"},
    ],
    "hint1": "想想放大区要让载流子顺利注入又被收集。", "hint2": "",
    "demonstration": "放大区：发射结正偏、集电结反偏。",
    "explanation": "正偏发射结注入载流子，反偏集电结收集载流子。",
}


def test_good_draft_passes_validation():
    concept = knowledge.get_concept("bjt_basics")
    assert draft_items.validate_draft(GOOD, concept, "state_confusion") == []


def test_untagged_wrong_option_fails_validation():
    concept = knowledge.get_concept("bjt_basics")
    bad = json.loads(json.dumps(GOOD))
    del bad["options"][1]["misconception"]
    errors = draft_items.validate_draft(bad, concept, "state_confusion")
    assert any("misconception" in e for e in errors)


def test_target_misconception_must_be_covered():
    concept = knowledge.get_concept("bjt_basics")
    bad = json.loads(json.dumps(GOOD))
    for o in bad["options"]:
        if o.get("misconception") == "state_confusion":
            o["misconception"] = "voltage_amplifier_myth"
    errors = draft_items.validate_draft(bad, concept, "state_confusion")
    assert any("state_confusion" in e for e in errors)


def test_draft_lands_in_drafts_not_content(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "API_KEY", "test")
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: json.dumps(GOOD))
    path = draft_items.draft_for("bjt_basics", "state_confusion", out_dir=tmp_path)
    assert path.parent == tmp_path and path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "UNREVIEWED" in saved["status"]


def test_no_key_no_draft(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "API_KEY", "")
    with pytest.raises(SystemExit):
        draft_items.draft_for("bjt_basics", "state_confusion", out_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []
