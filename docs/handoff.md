# 交接文档：引导式学习 Agent（guided-learning-agent）

> 交出方：Muse（ark 的个人 agent），写于 2026-11-07。
> 交出方与接手方**不共享记忆**，本文件即全部交接。文中数字均为实测并注明口径；
> “已验证 / 未验证 / 待拍板”严格分开，不要把计划读成成果。

## 1. 项目一句话

三人小组（ark 为负责人之一）的网页版**引导式学习 Agent**，目标为公开发布的
开源级项目（MIT）。首课为华东理工大学《现代电子技术与系统》的**三极管基本
放大电路**。教学法：诊断 → 分层提示/示范 → 引导练习 → **无提示独立测验**，
“掌握”只认独立测验证据；选择题错误选项绑定**误区码**（misconception code）；
LLM 只做判分与文案，教学决策由规则状态机负责、可解释、可测试。

- 仓库：https://github.com/fangfangzhouhang/guided-learning-agent （**Public**）
- 技术栈：Python + FastAPI + SQLite + 原生 HTML/CSS/JS（多页 hash 路由，
  `#/course` `#/study/<id>` `#/chat` `#/review` `#/profile`），无构建步骤
- 运行：`pip install -r requirements.txt` 后 `uvicorn app.main:app --reload`，
  浏览器开 http://127.0.0.1:8000 ；另有 Dockerfile
- 课程内容口径：以老师课件为准——rbe = 200Ω + (1+β)·26/IE、UBE 取 0.7V；
  课程包在 `content/*.json`，加新课不改代码

## 2. 当前状态（2026-11-07 实测）

- **GitHub main 最新提交 `abce6db`**：V0.5 RAG + 三项升级（见下）。
  关键历史提交：`bca1bca` 评测 harness → `9986ccb` 判分加固（V0.3.3）→
  `5e35a49` Elo+起草工具（V0.35）→ `71ebce7` FSRS 复习（V0.4）→
  `f575cf0` V0.5 RAG → `abce6db` 升级批。
- ⚠️ Muse 侧的本地目录不是完整 git 检出，历史推送走 GitHub API 完成；
  **以 GitHub main 为唯一权威**，本地副本只作工作区。
- 已验证（本机）：pytest **35/35**；评测三层数字见第 6 节。
- **未验证/未发生**：GitHub CI 从未成功运行——ark 的 GitHub 账户 billing
  被锁，workflow 启动即失败，只有 ark 本人能解（Settings → Billing）；
  从未打 git tag / 发 Release；尚无真实学生使用数据。

## 3. 红线与协作规矩（不可自行推翻）

1. **掌握判定只来自无提示独立测验**。LLM 判分、Elo 评分都不许影响掌握结论。
2. **密钥永不进仓库**。项目机器在根目录 `.env` 写 `LLM_API_KEY=`（DeepSeek）；
   缺 key 时应用照常运行，只是判分退回离线关键词兜底、问老师无 RAG 依据。
   （Muse 环境另有 custom.deepseek 安全连接器可直连 DeepSeek 跑评测，
   其他环境用 .env 即可，不要去找聊天记录里的旧 key——它从未被存储。）
3. **题目草稿永不自动入库**：`tools/draft_items.py` 产物只进 gitignored 的
   `drafts/`，进 `content/` 必须双人审核（协议在 CONTRIBUTING.md）。
4. **LangGraph 迁移由团队学完后亲手做**，agent 不许代劳——这是学习目标
   本身（见 `docs/learning-path.md`）。Dify 明确不学。
5. **RAG 拒答铁律**：检索无证据时老师必须明说“课程资料里没查到”，
   不许编造公式与数值（阈值与实现见 `docs/rag.md`）。
6. 推送、改仓库等对外动作需 ark 批准后再做；给老师/队友看的材料
   不出现 AI 名字。

## 4. 设计口径：借什么、不借什么（调研定版，勿重开）

完整调研：`~/workspace/research_notes/guided-learning-agent-tech-research-20261106-1647/report.md`
（在 Muse 工作区，仓库内摘要在 `docs/implementation-plan.md`）

- **已借**：FSRS 复习调度（默认参数；其参数优化器需数百条复习日志，
  数据不够前不许开）；Elo 双评级做题目难度标定（仅首次作答计入）；
  Prometheus 的量表式判分提示词形状 + 三票自洽投票；LearnLM/Khanmigo
  教学提示词（先提示、答错后直白纠正，不要“永不给答案”式死板苏格拉底）。
- **不借**：DKT/神经知识追踪（数据量下逻辑回归不输 DKT，Gervet et al.
  JEDM 2020，且本项目无此量级数据）；本地自托管判分模型（API 判分已
  0.967，性价比不成立）；m3e 向量模型（许可证与 MIT 发布冲突）；
  pyBKT / IRT（触发条件：数千条真实作答，现在没有）。
- 2026-11-07 约束变更：**“普通笔记本能跑”约束已取消**（ark 可开显卡），
  功能优先；但基于数据的裁决（DKT 等）不因算力变化而变。

## 5. 系统地图（文件级）

| 路径 | 职责 |
|---|---|
| `app/main.py` | FastAPI 路由与静态托管；`/api/status` 自诊断（只回布尔，不泄 key） |
| `app/tutor.py` | 教学状态机（诊断/提示/练习/独立测验）、问老师对话、追问查询改写 |
| `app/storage.py` | SQLite 全部表：进度、作答、Elo、复习卡、聊天记录 |
| `app/knowledge.py` | 课程包（`content/*.json`）加载与校验 |
| `app/llm.py` | DeepSeek 客户端、开放题判分（量表提示+投票，失败退回关键词） |
| `app/elo.py` | Elo 双评级（K_student=32 / K_question=8） |
| `app/review.py` | FSRS 复习：学完建卡、到期队列、复测结果回写调度 |
| `app/rag.py` | 混合检索：bge-large 向量（sqlite-vec）+ 自实现 BM25，RRF 融合 → bge-reranker-large 重排；阈值下全丢=无证据 |
| `content/bjt.json` | 唯一课程包：7 个知识点、题目、误区库 |
| `tools/build_rag.py` | 下载模型到 `models/`（约 3.5GB，gitignore）、建 `rag.db` 索引、`--check` 跑检索评测 |
| `tools/draft_items.py` | 按误区码起草题目，结构校验后只写 `drafts/` |
| `evals/` | harness：`teaching_cases.json`（行为剧本）、`golden_explanations.json`（判分金标 30 份）、`rag_cases.json`（检索评测 11 条）、`run_evals.py`、`report.json` |
| `docs/` | `evals.md` 评测口径、`rag.md` RAG 说明、`implementation-plan.md` 实施计划、`learning-path.md` 团队学习路线、`roadmap-opensource.md` 版本路线 |
| `contracts/api.md` | 前后端接口契约 |

## 6. 验证方法与口径（结论表述纪律）

跑法：`python -m pytest -q`；`python -m evals.run_evals`；
`python -m tools.build_rag --check`（需先建索引）。

当前基线（2026-11-07，本机实测，全部可复现）：

| 层 | 内容 | 结果 |
|---|---|---|
| A 教学案例 | 8 条脚本学生走真实引擎，断言掌握判定/误区归因/复习队列等 | **8/8** |
| B 判分一致率 | 金标 30 份（完整/残缺/误区/灌水/离题）对人工标注 | LLM **29/30 = 0.967**；离线关键词 **17/30 = 0.567**（仅兜底定位） |
| RAG 检索 | 11 条（9 在题含公式符号题 + 2 离题） | **11/11**，离题正确无证据 |

- 唯一判分分歧 `ge09` 已复议定案：题面要求结合公式，金标维持“不通过”，
  判分器从宽记为已知边界，**不要改标**（细节在金标文件 note 字段）。
- 已知坑：CrossEncoder.predict 输出已是概率，**不要再套 sigmoid**
  （踩过，评测从 8/8 掉到 5/8）；FSRS 的 PyPI 包名就是 `fsrs==6.3.2`；
  模型从 HuggingFace 直下易断连，用 `curl -C -` 逐文件续传；
  pip 装 torch 在小 /tmp 环境要改 TMPDIR 且用 CPU 版索引。
- 纪律：**自动测试通过 ≠ 真人验收**。本项目尚无真实用户数据，一切
  “效果好”的表述目前只有评测集口径。

## 7. 未决事项

| 事项 | 卡在谁 | 说明 |
|---|---|---|
| 知识库扩张到全课程（先产“半导体器件”章） | ark 去拿老师全课程目录/其余课件 | 已暂停，课件到前不要自行按通用教材扩章 |
| GitHub CI 恢复 | ark 本人 | billing 锁，agent 无能为力 |
| FSRS 优化器 / BKT / IRT | 真实使用数据 | 先拉队友同学真用，攒作答与复习日志 |
| git tag / Release | ark 拍板 | 提议过 v0.3.1，未答复，现版本已远超，不要自作主张打 |
| 老师课件 PDF 入 RAG | 同第一项 | 课件到后把 PDF 切块入索引，流程同 `build_rag` |

## 8. 候选任务（接手可直接开工，但先向 ark 确认范围）

1. 课件到位后：老师 PDF 入 RAG + “半导体器件”章骨架与误区码设计
   （生产流程：LLM 起草 → 双人审核 → 入库，铁律见第 3 节）。
2. 金标集随新题型继续扩（目标 50 份），保持每类探针都有新变体。
3. 组织队友/同学试用并回收反馈与数据（非代码活，价值最高）。

## 9. 沟通偏好（ark）

- 执行与进度：**短、直接、先做完再报结果**；学习与科研问题：详细、系统、
  从第一性原理讲。
- 数字必须带来源与口径，禁止“差不多/基本一致”式表述；不确定就明说
  未验证。用了某个 skill 要明说用了哪个。
- 成品与重要进度节点习惯同步到 ark 的 Gmail（ffzh0625@gmail.com），
  他的其他 AI 靠邮箱对齐上下文。
