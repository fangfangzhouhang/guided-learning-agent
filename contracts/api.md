# 接口契约 v0.1（三组共同遵守，变更需三组负责人确认）

## HTTP API

- `GET /api/course` → 课程信息 + 知识点列表（含先修、要点、来源，不含题目答案）
- `GET /api/progress/{student}` → `{student, mastery: {concept_id: {status, evidence}}}`
  - status ∈ `mastered` / `passed_with_help` / `needs_review`
- `POST /api/sessions` `{student, concept_id}` → `{session, message, question, stage}`
  - question 只包含 `id / prompt / options[]`（纯文本），不下发对错与误区信息
- `POST /api/sessions/{id}/hint` → `{hint_level, hint, demonstration?}`
  - stage=test 时返回 400（独立测验禁用提示）
- `POST /api/sessions/{id}/answer` `{option_index, confidence?}` →
  `{correct, misconception, explanation, feedback, action, next_stage?, question?, demonstration?, mastery?}`

## 组间函数接口

- B → A：`knowledge.get_question(concept_id, stage)`、`knowledge.get_concept(concept_id)`
- A → C：`storage.record_event(...)`、`storage.set_mastery(...)`（判定权只在 A）
- C 只负责存取与展示，不在存储层写任何"掌握"规则

## 题目数据格式（content/*.json）

每个知识点含 `questions.diagnose / guided / test` 三题；每题含
`prompt / options[] / hint1 / hint2 / demonstration / explanation`，
错误选项必须带 `misconception` 编码，且该编码必须在知识点的
`misconceptions` 字典里有对应的人话解释。
