"""Knowledge layer: loads the structured course content and serves it.

Group B (knowledge resources) owns this module and content/bjt.json.
The tutor and the API only ever read knowledge through these functions,
so course content can be extended (e.g. from teacher PPTs) without
touching teaching logic.
"""
from __future__ import annotations

import json
from pathlib import Path

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"

# Course-pack architecture: every content/*.json file is one course pack
# with the same schema (course + concepts). Drop a new pack into content/
# and it becomes available without touching code — this is how the project
# grows from one chapter to a full course, and how contributors add courses.
COURSES: dict[str, dict] = {}
CONCEPTS: dict[str, dict] = {}
for _path in sorted(CONTENT_DIR.glob("*.json")):
    with _path.open(encoding="utf-8") as fh:
        _data = json.load(fh)
    COURSES[_data["course"]["id"]] = _data["course"]
    for _c in _data["concepts"]:
        CONCEPTS[_c["id"]] = _c
    if "concepts" not in COURSES[_data["course"]["id"]]:
        COURSES[_data["course"]["id"]]["concepts"] = _data["concepts"]

_DEFAULT_ID = next(iter(COURSES))
COURSE = COURSES[_DEFAULT_ID]
_DATA = {"course": COURSE, "concepts": COURSE["concepts"]}


def list_courses() -> list[dict]:
    return [
        {"id": c["id"], "title": c["title"], "description": c["description"],
         "concept_count": len(c["concepts"])}
        for c in COURSES.values()
    ]


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


def get_question(concept_id: str, stage: str, index: int = 0) -> dict | None:
    concept = CONCEPTS.get(concept_id)
    if not concept:
        return None
    pool = concept["questions"].get(stage) or []
    if index < 0 or index >= len(pool):
        return None
    return pool[index]


def stage_size(concept_id: str, stage: str) -> int:
    concept = CONCEPTS.get(concept_id)
    if not concept:
        return 0
    return len(concept["questions"].get(stage) or [])


def public_question(question: dict) -> dict:
    """Strip answers/rubrics before sending to the client."""
    qtype = question.get("type", "mcq")
    out = {"id": question["id"], "type": qtype, "prompt": question["prompt"]}
    if qtype == "mcq":
        out["options"] = [opt["text"] for opt in question["options"]]
    elif qtype == "numeric":
        out["unit"] = question.get("unit", "")
    return out
