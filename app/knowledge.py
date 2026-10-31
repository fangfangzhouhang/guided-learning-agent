"""Knowledge layer: loads the structured course content and serves it.

Group B (knowledge resources) owns this module and content/bjt.json.
The tutor and the API only ever read knowledge through these functions,
so course content can be extended (e.g. from teacher PPTs) without
touching teaching logic.
"""
from __future__ import annotations

import json
from pathlib import Path

CONTENT_PATH = Path(__file__).resolve().parent.parent / "content" / "bjt.json"

with CONTENT_PATH.open(encoding="utf-8") as fh:
    _DATA = json.load(fh)

COURSE = _DATA["course"]
CONCEPTS: dict[str, dict] = {c["id"]: c for c in _DATA["concepts"]}


def list_concepts() -> list[dict]:
    """Public view of all concepts (no answers leaked)."""
    out = []
    for c in _DATA["concepts"]:
        out.append(
            {
                "id": c["id"],
                "title": c["title"],
                "summary": c["summary"],
                "key_points": c["key_points"],
                "prerequisites": c["prerequisites"],
                "sources": c["sources"],
            }
        )
    return out


def get_concept(concept_id: str) -> dict | None:
    return CONCEPTS.get(concept_id)


def get_question(concept_id: str, stage: str) -> dict | None:
    concept = CONCEPTS.get(concept_id)
    if not concept:
        return None
    return concept["questions"].get(stage)


def public_question(question: dict) -> dict:
    """Strip correctness/misconception data before sending to the client."""
    return {
        "id": question["id"],
        "prompt": question["prompt"],
        "options": [opt["text"] for opt in question["options"]],
    }
