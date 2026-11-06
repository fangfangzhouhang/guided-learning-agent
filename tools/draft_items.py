"""Misconception-first question drafting tool.

Drafts ONE new multiple-choice question whose wrong options are each
generated from a named misconception code, then writes it to drafts/ for
human review. It NEVER writes into content/ — the iron rule of the
content pipeline: LLM drafts, two humans review, only then does a
question enter the course pack by hand (see CONTRIBUTING.md).

Usage (needs LLM_API_KEY configured):
  python -m tools.draft_items --concept bjt_basics --misconception state_confusion
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import knowledge, llm  # noqa: E402

DEFAULT_OUT = ROOT / "drafts"


def validate_draft(draft: dict, concept: dict, target_code: str) -> list[str]:
    """Structural + pedagogy checks a draft must pass before review."""
    errors: list[str] = []
    if draft.get("type", "mcq") != "mcq":
        errors.append("draft must be an mcq question")
    for field in ("prompt", "hint1", "explanation"):
        if not str(draft.get(field, "")).strip():
            errors.append(f"missing or empty: {field}")
    options = draft.get("options") or []
    if len(options) < 3:
        errors.append("need at least 3 options")
    correct = [o for o in options if o.get("correct")]
    if len(correct) != 1:
        errors.append(f"exactly one correct option required, got {len(correct)}")
    codes = concept["misconceptions"]
    covered = set()
    for o in options:
        if o.get("correct"):
            continue
        code = o.get("misconception")
        if code not in codes:
            errors.append(f"wrong option {o.get('text', '')[:20]!r} has no valid "
                          f"misconception code (got {code!r})")
        else:
            covered.add(code)
    if target_code not in covered:
        errors.append(f"no wrong option targets the requested misconception {target_code}")
    return errors


def _draft_prompt(concept: dict, code: str) -> list[dict]:
    example = concept["questions"]["diagnose"][0]
    codes = "\n".join(f"  {c}: {t}" for c, t in concept["misconceptions"].items())
    return [
        {"role": "system", "content": (
            "你是现电课程的命题助手。按要求起草一道选择题，只输出 JSON，不要其他文字。"
            "JSON 字段：type='mcq', id（用 'draft' 开头）, prompt, options（数组，"
            "每项 {text, correct: true/false, misconception: 误区码或省略}）, "
            "hint1, hint2, demonstration, explanation。"
            "要求：恰好一个正确项；每个错误项必须对应一个真实存在的误区码，"
            "且错法正是那个误区的典型表现；数值题的数字要算对；解析说清为什么对、"
            "典型错误错在哪。风格参考给定例题。")},
        {"role": "user", "content": (
            f"知识点：{concept['title']}——{concept['summary']}\n要点：{'；'.join(concept['key_points'])}\n"
            f"本题重点考查的误区：{code}：{concept['misconceptions'][code]}\n"
            f"该知识点可用的误区码：\n{codes}\n"
            f"例题（只学风格，不要照抄）：{json.dumps(example, ensure_ascii=False)}")},
    ]


def draft_for(concept_id: str, code: str, out_dir: Path = DEFAULT_OUT) -> Path:
    if not llm.enabled():
        raise SystemExit("LLM_API_KEY is not configured — the drafting tool "
                         "needs the LLM. Nothing was written.")
    concept = knowledge.get_concept(concept_id)
    if code not in concept["misconceptions"]:
        raise SystemExit(f"unknown misconception code {code!r} for {concept_id}; "
                         f"known: {sorted(concept['misconceptions'])}")
    out = llm._chat(_draft_prompt(concept, code), temperature=0.7, timeout=60)
    if not out:
        raise SystemExit("LLM call failed; nothing was written.")
    try:
        start, end = out.index("{"), out.rindex("}") + 1
        draft = json.loads(out[start:end])
    except Exception:
        raise SystemExit("LLM did not return parseable JSON; nothing was written.")
    errors = validate_draft(draft, concept, code)
    if errors:
        raise SystemExit("draft failed validation, NOT saved:\n- " + "\n- ".join(errors))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{concept_id}_{code}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "status": "DRAFT-UNREVIEWED — 双人复核通过前禁止入库",
        "concept": concept_id, "target_misconception": code,
        "question": draft,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Draft one misconception-tagged question")
    ap.add_argument("--concept", required=True)
    ap.add_argument("--misconception", required=True)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    path = draft_for(args.concept, args.misconception, args.out)
    print(f"draft written to {path} — needs two-person review before entering content/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
