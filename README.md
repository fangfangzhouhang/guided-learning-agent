# 引导式学习 Agent · 现电 · 三极管放大电路

> **Guided Learning Agent** — an open-source AI tutor that teaches step by
> step instead of handing out answers. It diagnoses the exact misconception
> behind a wrong answer, gives layered hints and worked demonstrations, and
> only marks a topic as *mastered* when the student passes an independent,
> hint-free variant test. Ships with a full course pack for BJT transistor
> amplifier circuits; new courses are data files, not code changes.

一位有耐心、懂你的 AI 老师：不直接给答案，而是按
**诊断 → 引导/示范 → 练习 → 独立测验** 的闭环一步步带着学。
只有独立测验（无提示）通过，才判定为真正掌握；答错会定位到具体的
概念误区，而不是只说"错了"。它还记得每个学生反复错的地方，
会在画像里给出下一步复习建议，在自由提问时有针对性地多追问一步。

当前课程：**现电 · 三极管放大电路**，共 7 个知识点、33 道题（先修顺序）：

1. 三极管结构与放大原理
2. 放大电路的性能指标
3. 静态工作点与偏置电路
4. 微变等效电路
5. 共射放大电路分析（Av、Ri、Ro）
6. 失真与静态工作点的稳定
7. 共集、共基与三种组态对比

题型包括选择题（错误选项绑定误区）、计算填空题（数值容差判分，
例题风格对齐老师课件）和开放题（大模型按要点判读，离线时关键词规则兜底）。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000 即可使用。测试：

```bash
pip install pytest && python -m pytest -q
```

或者用 Docker 一键运行：

```bash
docker build -t gla .
docker run -p 8000:8000 -e LLM_API_KEY=<你的DeepSeek密钥> gla
```

不传 `LLM_API_KEY` 时为离线模式：课程学习闭环完整可用，「问老师」
切换为基于知识库的引导模式。贡献方式见 `CONTRIBUTING.md`，
团队学习路径见 `docs/learning-path.md`，开源路线见
`docs/roadmap-opensource.md`。本项目以 MIT 协议开源（见 `LICENSE`）。

## 已实现功能（对应产品要求）

- **知识地图与先修关系**：左侧按先修顺序列出知识点、要点与资料来源
- **诊断定位**：每个知识点先做诊断题，每个错误选项都绑定一个误区编码
- **分层提示**：提示 1（思路）→ 提示 2（公式/链条）→ 完整示范；用提示会被记录
- **示范教学**：诊断答错自动给出完整示范，照顾零基础，而不是一味追问
- **独立测验**：每个知识点最后一题是变式独立测验，此阶段禁用提示
- **掌握判定靠证据**：测验通过且提示 ≤1 次记为"已掌握"；提示多记为
  "帮助下通过"；测验未过记为"待复习"，绝不凭一句"我懂了"判定
- **信心校准**：答题前可填信心等级，系统会指出"有信心但答错"这类认知错觉
- **学习记录**：SQLite 保存每次作答、误区、提示次数与掌握状态，可追溯
- **问老师（自由提问）**：接入大模型后可自由打字提问，老师按
  “先定位、再引导、卡住才示范”的方式回答，并结合该学生的误区画像追问；
  无密钥时自动切换离线引导模式（按知识库给出抓手和问题，绝不假装在讲解）
- **开放题判读**：配置 `LLM_API_KEY`（见 `.env.example`，兼容 DeepSeek 等
  OpenAI 兼容接口）后，开放题由大模型按参考要点判读并点评；
  教学流程的决策始终由可解释的规则状态机做出，无密钥时完全离线可用
- **我的画像**：掌握情况、反复出现的误区 Top 榜、下一步推荐（先复习
  未通过的知识点），推荐会直接出现在知识地图下方

## 结构与分工（三组边界）

| 模块 | 负责组 | 说明 |
|---|---|---|
| `app/tutor.py` | A 智能教学组 | 教学决策状态机、误区诊断、掌握判定 |
| `app/llm.py` | A 智能教学组 | 模型调用（只润色文案，不做决策） |
| `app/knowledge.py` + `content/` | B 知识资源组 | 知识点、题库、误区库、资料来源 |
| `app/storage.py` | C 产品工程组 | 学习记录存储（只记录，不判定） |
| `app/main.py` + `static/` | C 产品工程组 | API 与网页界面 |

接口契约见 `contracts/api.md`。后续接入老师 PPT 时，只需按
`content/bjt.json` 的格式扩充知识点与题目，不需要改教学逻辑。

## 路线图

- V0.1 ✅：单课程闭环、规则状态机、SQLite、网页端
- V0.2 ✅：按老师课件扩充题库（33 题）、新增性能指标知识点、计算题
- V0.3 ✅（当前）：自由提问的耐心教师（结合学生画像）、开放题判读、
  学习者画像与复习推荐、手机端适配
- 下一步：间隔复习调度、教师看板（全班误区统计）、云部署后做
  小范围对照试用（升级细节见 `docs/roadmap-v2.md`）
