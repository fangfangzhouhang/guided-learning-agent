"""Elo dual ratings — learner modelling lite (after Pelánek 2016).

Every *first* attempt at a question is treated as a match between the
student and the question: the student "wins" by answering correctly.
Both ratings move after each match, so from the very first student the
system accumulates two useful signals with ~30 lines and no training:

- a continuous student ability estimate (complements the categorical
  mastery states, which stay the only basis for mastery decisions);
- an online item-difficulty calibration: questions real students fail
  drift up in rating, replacing hand-guessed difficulty labels.

Deliberate simplifications (documented, revisit when data grows):
- only the first attempt per question per session counts (guided retries
  after a demonstration are practice, not evidence);
- the question's K is small (8) so difficulty estimates move slowly and
  stay stable; the student's K is 32;
- ratings never feed mastery decisions — red line 1 in the roadmap:
  mastery comes from the independent test, not from a rating.
"""
from __future__ import annotations

from . import storage

DEFAULT_RATING = 1200.0
K_STUDENT = 32.0
K_QUESTION = 8.0


def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(rating_a - rating_b) / 400.0))


def record_attempt(student: str, concept_id: str, question_id: str,
                   correct: bool) -> dict:
    """Update both ratings after a first attempt; return the new values."""
    qkey = f"{concept_id}/{question_id}"
    s_rating, s_attempts = storage.get_rating("student", student)
    q_rating, q_attempts = storage.get_rating("question", qkey)
    exp_student = _expected(s_rating, q_rating)
    score = 1.0 if correct else 0.0
    s_new = s_rating + K_STUDENT * (score - exp_student)
    q_new = q_rating + K_QUESTION * (exp_student - score)
    storage.set_rating("student", student, s_new, s_attempts + 1)
    storage.set_rating("question", qkey, q_new, q_attempts + 1)
    return {"student_rating": round(s_new, 1), "question_rating": round(q_new, 1),
            "question_attempts": q_attempts + 1}
