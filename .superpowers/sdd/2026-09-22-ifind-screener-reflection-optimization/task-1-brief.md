# Task 1 Brief: 写 ADR-0008 文档（先行定义术语）

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 是一个本地 A 股投资辅助工具。前一轮头脑风暴 + 写作已完成：
- Spec: `docs/superpowers/specs/2026-09-22-ifind-screener-reflection-optimization-design.md`（commit `ff5d275`）
- Plan: `docs/superpowers/plans/2026-09-22-ifind-screener-reflection-optimization.md`（commit `3d7b9a4`）

本任务是 plan 的第 1 个 task（20 个中的 1 个），目的是**先定义术语**——写 ADR-0008 让项目后续改动有据可查。

## Global Constraints (本任务相关)

- 项目已有 ADR-0006 (screener) 和 ADR-0007 (watchlist)，本 ADR-0008 沿同样风格
- ADR 必须包含：状态、背景、决策、拒绝方案、数据模型、影响
- **本地有 22 个未提交改动 + 新迁移 `k3f32g5h6i7j8_drop_kline_cache.py`**——本任务不涉及这些文件，无需 stash/commit
- 工作分支: `main`（用户已 explicit consent 在 main 上跑）
- Commit message 风格: `docs(adr): <中文描述>`

## Task Description

### Files
- Create: `docs/dev-log/ADR-0008-ifind-screener-reflection-optimization.md`
- Modify: `docs/dev-log/decisions-index.md`（追加 ADR-0008 条目）

### Interfaces
- Consumes: 无
- Produces: ADR-0008 文档 + decisions-index 条目

### Steps

#### Step 1: 读 ADR-0007 + decisions-index

读 `docs/dev-log/ADR-0007-screener-watchlist.md` 和 `docs/dev-log/decisions-index.md`，熟悉格式。

#### Step 2: 写 ADR-0008

新建 `docs/dev-log/ADR-0008-ifind-screener-reflection-optimization.md`，结构（仿 ADR-0006/0007）：

```markdown
# ADR-0008: iFinD 驱动现有模块优化（事件因子 / 基本面兜底 / 消息面提示）

## 状态：已采用（2026-09-22）

## 背景
现有 screener v2.6 (ADR-0006) 与 watchlist v2.6.1 (ADR-0007) 已上线,
但 screener 仅看资金流 + 量比 + 涨速 + 板块强度 4 项纯技术因子,
缺失"事件命中"维度; 跑出 Top N 后无法剔除"技术面强势但基本面差"的伪强势票;
ReflectionCard 22:00 弹窗缺少消息面上下文。

iFinD（thsifind 数据接口, 已接入工具栏）提供:
- search_trending_news: 热门事件驱动资讯(时效性强)
- search_securities: 智能选股(基于财务/估值/行业过滤)
- search_news + search_notice: 财经新闻 + 公告

## 决策
新增 3 项 ifind 数据接入, 全部走"接现有模块不开新功能"原则:
1. screener 加事件因子加权(第 5 因子, 0/8/15 三档)
2. screener Top N 末尾追加基本面兜底过滤(hard gate)
3. ReflectionCard 22:00 加消息面提示行(失败静默)

## 拒绝方案
- ❌ ifind LLM 调用: thsifind 是数据接口, 不是 LLM
- ❌ ifind 智能选股另起范式: screener 已有评分体系
- ❌ 实时盘中预警: 盘后复盘场景, 不需要实时
- ❌ ifind 多账户: 个人单机工具
- ❌ ifind 自动调度: 用户主动触发, 不后台跑

## 数据模型
新增 2 张表 + 2 个 Alembic 迁移:
- event_factor_cache(trade_date PK, event_keywords_json, stock_codes_json, fetched_at, ifind_calls, created_at, updated_at)
- reflection_context_cache(fetch_date PK, context_json, fetched_at, ifind_calls, created_at, updated_at)
- screener_picks 表新增列 fundamental_filter_status('passed'/'kicked'/NULL)

## 影响
新增 7 个文件, 修改 6 个文件, 扩 4 个测试文件。
screener 总分上限 155 → 170; 失败语义: A/C 静默不阻断, B 失败不展示 Top N。
完整设计: docs/superpowers/specs/2026-09-22-ifind-screener-reflection-optimization-design.md
```

#### Step 3: 追加 decisions-index

编辑 `docs/dev-log/decisions-index.md`，按现有顺序追加：

```markdown
- ADR-0008 — iFinD 驱动现有模块优化（事件因子 / 基本面兜底 / 消息面提示），2026-09-22
```

#### Step 4: Commit

```bash
git add docs/dev-log/ADR-0008-ifind-screener-reflection-optimization.md docs/dev-log/decisions-index.md
git commit -m "docs(adr): ADR-0008 ifind 驱动现有模块优化"
```

## Acceptance Criteria

- ADR-0008 文件存在且内容符合 Step 2 模板
- decisions-index.md 含 ADR-0008 条目
- 1 个 commit 落在 main 上（git log 验证）
- 本地 22 个未提交改动未受影响

## Report File

**写报告到**: `.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-1-report.md`

报告应包含：
- 实现了什么（或尝试了什么 if blocked）
- 测试了什么 + 结果
- 文件变更列表
- self-review 发现
- 任何 issues 或 concerns