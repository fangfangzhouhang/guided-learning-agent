# Contributing

Thanks for helping build an open-source guided learning agent!

## Ground rules

- **Teaching decisions must stay explainable.** Anything that decides
  "what to teach next / whether the student has mastered this" belongs in
  `app/tutor.py`'s state machine, not inside an LLM prompt.
- **Never commit secrets.** API keys go in a local `.env` only (gitignored).
- **Course content is data, not code.** Add or fix questions in
  `content/*.json`. Every wrong MCQ option must carry a `misconception`
  code that exists in the concept's `misconceptions` map, and every
  question needs an `explanation`. Wrong teaching content is worse than
  a code bug — get a second person to check new questions.

## Workflow

1. Branch from `main`: `git switch -c feat/short-name`
2. Make the change, add/adjust tests in `tests/`
3. Run `python -m pytest -q` locally (must pass offline, no key needed)
4. Open a PR; CI must be green and one reviewer must approve

## Adding a course pack

Copy an existing file in `content/`, keep the schema
(`course` + `concepts` with `questions.diagnose/guided/test` pools),
and it will be picked up automatically. See `contracts/api.md` for the
question format.
