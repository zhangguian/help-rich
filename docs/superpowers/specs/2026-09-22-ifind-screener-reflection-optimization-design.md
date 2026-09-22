# 设计文档: iFinD 驱动现有模块优化（2026-09-22）

> **状态**: 待评审
> **目的**: 反向利用 thsifind 工具能力（数据源），优化三个现有模块
> **范围**: screener（2 项改动） + reflection（1 项改动）
> **不在范围**: 5 个被显式排除的 ifind 用法（详见 §2）
> **核心原则**: 失败就是失败（无降级矩阵）

---

## 1. 背景与动机

### 1.1 项目现状（基于 2026-09-22 实际代码扫描）

仓库 `D:/zga-study/rich`（branch `main`，HEAD `5a7666e feat(screener): 上线v2.6.1盘后选股+观察池完整模块`）是一个本地单机的 A 股投资辅助工具**，**v0.4 后端 + Next.js 前端，技术栈：

- **后端**: FastAPI 0.115 + SQLAlchemy 2.0 + Pydantic 2 + aiosqlite + cryptography + loguru；分层结构 `api`/`core`/`models`/`repositories`/`services`，外加平级 `data`/`llm`/`ocr`
- **前端**: Next.js 14.2 App Router + React 18 + TS 5 + Tailwind 3.4 + Zustand 5 + Zod 4 + axios；图表混合 `lightweight-charts`（K线）+ `echarts`；`pnpm gen-types` 从 OpenAPI 自动生成前端类型
- **数据源**: `app/data/{sina.py, tencent.py}`（行情）
- **LLM**: `app/llm/{factory.py, deepseek.py, doubao.py, minimax.py}`（Provider 工厂）
- **测试**: 后端 ~35 个 pytest，按业务名整齐对应
- **本地未提交改动**: 涉及 22 个文件，新迁移 `k3f4g5h6i7j8_drop_kline_cache.py` 已删除 DB 层 KlineCache，所有 K 线直连 provider

### 1.2 现有"复盘"链路（精读）

- `app/services/replay_service.py`: 单股窗口聚合（1d/3d/5d/10d/20d/60d），**100% 基于本地 DB**（流水 + 自评 + 持仓占比 + LLM 评语），无任何外部市场上下文
- `app/services/daily_analysis_service.py`: 每日分析存档 + 信号胜率，K 线来自 sina，**无第三方基本面/事件上下文**
- `app/services/news_service.py`: **仅有 sina 7×24 快讯**，无类型化 / 无股票聚合 / 无定时存档
- `app/core/prompts.py`: "克制的复盘助手"红线（不预测 / 不买卖 / 引用数据 / 末尾"以上不构成投资建议"）

### 1.3 现有 screener（精读）

- `app/services/screener_service.py`: v2.6 盘后选股，**后台 15:30 自动跑**（`lifespan` 中 `_asyncio.create_task(start_screener_scheduler())`）
- 评分因子（`core/config.py` 可调，`services/scoring.py` 实现）:
  - `main_inflow_score` (0~60)
  - `volume_ratio_score` (0~40)
  - `momentum_score` (0~30)
  - `sector_strength_score` (0~25)
  - **满分 155，纯技术面**
- 选股池: 沪深 300 + 中证 500（`scripts/init_index_constituents.py`）
- ADR-0006 决策: 拒绝"全市场 5000+ 扫描"、"自定义条件编辑器"、"筛选时自动调 LLM"、"stale_cache 兜底"

### 1.4 现有 ReflectionCard（精读）

- `frontend/src/components/reflection/ReflectionCard.tsx`: 22:00 弹窗"今日反思"
- 触发: 当前时间 ≥ 22:00 + 当日已录入 ≥ 1 笔交易
- 内容: 今日笔数 + 已实现盈亏 + 三个跳转链接（持仓 / 年账单 / 流水）
- **无消息面维度**

### 1.5 可用的 ifind 工具（已接入工具栏）

```
connector__thsifind__search_trending_news      # 热门事件驱动资讯(时效性强)
connector__thsifind__search_news               # 财经新闻片段
connector__thsifind__search_notice             # 公告语义查询
connector__thsifind__search_securities         # 智能选股(基于财务/估值/行业)
connector__thsifind__get_security_indicators   # 多市场综合指标(财务/估值)
connector__thsifind__get_stock_summary         # 上市公司基础信息
connector__thsifind__fetch_edb                 # 宏观经济/行业指标取数
```

---

## 2. 显式不做（来自 brainstorm 第 5 项 ❌ 决策）

| ❌ 项 | 字面决策 | 取/不取精华 |
|---|---|---|
| 不接 ifind LLM | thsifind 不是 LLM | 全部 |
| 不做 ifind 智能选股 | screener 已有 | **取精华**（改 B）|
| 不做实时行情预警 | 盘后场景 | **取精华**（改 C） |
| 不做 ifind 多账户 | 单用户单调用 | 不取 |
| 不做自动调度 | 用户主动 | 不取 |

**取精华的反向逻辑**：被排除的"整体方案"里有局部价值（事件因子 / 基本面兜底 / 消息面提示），把局部价值**植入现有模块**，不另起新功能。

---

## 3. 设计原则

1. **失败就是失败**：任一 ifind 调用失败 = 整个改动点的对应行为直接报错 / 显式空态，不写降级、不拼凑、不编造
2. **接现有模块，不开新功能**：改动 A / B 进 screener，改动 C 进 reflection
3. **不动 LLM Provider / 不动 prompt 风格红线**
4. **缓存策略统一**：每个 ifind 子调用结果当日缓存一次，跨日失效
5. **复用现有基建**：`app/core/db_lock.py`（并发写锁）、`app/core/logging.py`（loguru）、Alembic（无 create_all）

---

## 4. 三项改动详细设计

### 4.1 改动 A: screener 加"事件因子"加权

**目标**: 在 v2.6 screener 评分公式中**叠加第 5 因子**，让"今日被事件/概念驱动的票"获得额外加权。

**数据源**: `connector__thsifind__search_trending_news(time_scope='24小时', size=20)`

**触发时机**: screener 跑评分**之前**先拉一次当日热门事件 → 提取"涉及股票代码" → 与候选池求交集 → 给命中的票加权

**评分公式（`app/core/config.py` 新增）**:

```python
SCREENER_EVENT_FACTOR_WEIGHT = 15   # 事件命中加权分(0~15)
SCREENER_EVENT_KEYWORD_BLACKLIST = ["ST", "*ST", "退市"]  # 防止 ST 加权

# 新因子函数(在 app/services/scoring.py 新增)
def event_score(stock_code: str, event_stock_codes: set[str], event_keywords: set[str]) -> int:
    """事件命中分:0 / 8 / 15 三档"""
    if stock_code in event_stock_codes:
        return 15  # 出现在热门事件相关股列表里
    return 0
```

**总公式扩展**:

```python
score = main_inflow_score(0..60)         # 主资金流入
      + volume_ratio_score(0..40)        # 量比
      + momentum_score(0..30)            # 涨速+连续性
      + sector_strength_score(0..25)     # 板块资金强度
      + event_score(0..15)               # 事件命中(新增)
      # max 170(原 155 → 现 170)
```

**改动文件**:

| 操作 | 文件 | 说明 |
|---|---|---|
| 🆕 新增 | `backend/app/data/ifind_events.py` | 包装 `thsifind.search_trending_news`，归一为 `{fetched_at, event_keywords: set, stock_codes: set}` |
| 🆕 新增 | `backend/app/services/event_factor_service.py` | 业务编排（拉 ifind + 当日缓存 + 失败 fail-fast）|
| 🆕 新增 | `backend/app/repositories/event_factor_cache_repo.py` + `migrations/versions/<ts>_event_factor_cache.py` | 新表 `event_factor_cache`（key=`trade_date`，存 `event_keywords_json` + `stock_codes_json` + `fetched_at`）|
| 🆕 新增 | `backend/app/services/scoring.py` 新函数 `event_score` | 纯计算，无 I/O |
| ✏️ 修改 | `backend/app/core/config.py` | 新增 `SCREENER_EVENT_FACTOR_WEIGHT=15` 常量 |
| ✏️ 修改 | `backend/app/services/screener_service.py` | 评分循环里叠加 `event_score(...)`；screener 启动前先 `await build_event_factor_cache(today)` |
| ✏️ 修改 | `backend/tests/test_scoring.py` | 新增 `test_event_score` 用例 |
| 🆕 新增 | `backend/tests/test_event_factor_service.py` | mock ifind，覆盖：拉取成功 / 失败 / 缓存命中 / 当日失效 |

**不破坏**:
- 现有 4 因子分不变
- 总分上限从 155 → 170，**ADJUST 不需要**（下游只按相对分排序）
- `event_score` 返回 0 时等价于"无改动"，向后兼容

**失败语义**:
- `search_trending_news` 失败 → screener **当日不跑事件因子**（event_score 全 0） + log WARNING `"screener event factor unavailable today, running with 4-factor score"` + screener_runs 表新增列 `event_factor_status`（'ok' / 'unavailable'）

---

### 4.2 改动 B: screener Top N 基本面兜底过滤

**目标**: screener 跑出 Top N 后，**末尾追加一道基本面 gate**，剔除"技术面强势但基本面差"的伪强势票。

**数据源**: `connector__thsifind__search_securities(market='A股', query='扣非ROE>0 PE<行业均值 剔除ST')`

**触发时机**: screener 选出 Top N（默认 20）后，对每只票**单独查一次**基本面过滤条件。**并行批量**查 20 次 ifind，控制 1s/次超时。

**过滤规则（`app/core/config.py` 新增）**:

```python
SCREENER_FUNDAMENTAL_FILTER_ENABLED = True
SCREENER_FUNDAMENTAL_FILTER_QUERY = "扣非ROE>0 PE<行业中位数 剔除ST"
SCREENER_FUNDAMENTAL_KICKOUT_PENALTY = 30  # 不满足扣 30 分(强制踢出 Top N)
```

**业务逻辑（`app/services/screener_service.py` 新增 `_apply_fundamental_filter`）**:

```python
async def _apply_fundamental_filter(picks: list[ScreenerPick]) -> list[ScreenerPick]:
    """对 Top N 跑一次基本面过滤;失败直接抛出(不降级)"""
    if not SCREENER_FUNDAMENTAL_FILTER_ENABLED:
        return picks
    ifind_results = await asyncio.gather(
        *[isearch_securities_for_one(p.stock_code) for p in picks],
        return_exceptions=True,
    )
    # 任一失败 → 直接抛,不降级
    for i, r in enumerate(ifind_results):
        if isinstance(r, Exception):
            raise IfindUnavailable(f"基本面过滤失败: {picks[i].stock_code}: {r}")
    # 应用 penalty(命中筛条件 = 通过,不命中 = 扣 30 分)
    for pick, hit in zip(picks, ifind_results):
        if not hit:
            pick.score -= SCREENER_FUNDAMENTAL_KICKOUT_PENALTY
            pick.fundamental_filter_status = "kicked"
        else:
            pick.fundamental_filter_status = "passed"
    # 重排序
    picks.sort(key=lambda p: p.score, reverse=True)
    return picks
```

**改动文件**:

| 操作 | 文件 | 说明 |
|---|---|---|
| 🆕 新增 | `backend/app/data/ifind_fundamentals.py` | 包装 `search_securities` 查单只票的"是否命中筛条件" |
| ✏️ 修改 | `backend/app/services/screener_service.py` | 新增 `_apply_fundamental_filter`；在 `run_screener` 末尾调用 |
| ✏️ 修改 | `backend/app/models/orm.py` | `ScreenerPick` 表新增列 `fundamental_filter_status`（'passed'/'kicked'/NULL）+ Alembic 迁移 |
| ✏️ 修改 | `backend/app/core/config.py` | 新增 3 个常量 |
| ✏️ 修改 | `backend/tests/test_screener.py` | 新增 `test_apply_fundamental_filter`：mock ifind 全部成功 / 任一失败 / 全踢出 |
| ✏️ 修改 | `frontend/src/app/screener/page.tsx` | Top N 卡片新增一行 `基本面: ✓通过 / ⚠️被过滤`，对齐 v2.6 风格 |

**不破坏**:
- 默认开关 `SCREENER_FUNDAMENTAL_FILTER_ENABLED = True`，但**默认 query 极保守**（只剔除"扣非 ROE ≤ 0 或 ST"），不会大面积踢出
- 失败 = 整体抛 → screener run 标 `fundamental_filter_status='failed'`，前端展示空态

**失败语义**:
- 任一票基本面查失败 → screener run **整体失败**，不展示 Top N（fail-fast）
- LLM 同 screener 已有的"失败不阻断"风格**反向**：基本面是"硬门槛"，与 LLM 软建议不同

---

### 4.3 改动 C: ReflectionCard 22:00 加消息面提示

**目标**: 22:00 弹窗内加一行"今日是否有公告 / 重要新闻"提示，**引导用户去 `/replay-history` 看完整上下文**。

**数据源**: `connector__thsifind__search_notice`（按股票代码查当日公告）+ `search_news`（财经新闻聚合）

**触发时机**: ReflectionCard 现有 useEffect 内，**只在已有今日交易 + 22:00 + 未 dismiss 时**多触发一次 ifind 拉取。**不**改核心数据流。

**改动文件**:

| 操作 | 文件 | 说明 |
|---|---|---|
| 🆕 新增 | `backend/app/api/reflection_context.py` + `services/reflection_context_service.py` + `data/ifind_news.py`(事件 + 公告) | 暴露 `GET /api/reflection-context?date=today` 端点，返回 `{announcements_count, news_count, top_news_title}` |
| 🆕 新增 | `backend/app/repositories/reflection_context_cache_repo.py` + Alembic 迁移 | 新表 `reflection_context_cache`（key=`fetch_date`，存 `context_json`）|
| ✏️ 修改 | `frontend/src/components/reflection/ReflectionCard.tsx` | useEffect 多 fetch 一次 `/api/reflection-context`；成功时在卡片内多渲染一行 "📰 今日 N 条公告 / M 条新闻 → [查看]"，点击跳 `/replay-history?code=持仓列表第一只` |
| ✏️ 修改 | `frontend/src/lib/api/reflection-context.ts` | axios client 单文件 |
| 🆕 新增 | `backend/tests/test_reflection_context_service.py` | mock ifind，覆盖：拉取成功 / 失败（前端 banner 提示）|

**不破坏**:
- ReflectionCard 现有结构不变，**只在已触发弹窗 + 网络成功时**多加一行
- 22:00 触发逻辑不动
- ifind 失败 = 该行不渲染（前端吞错）

**失败语义**:
- 后端 ifind 拉取失败 → `GET /api/reflection-context` 返 `503`，**前端** `try/catch` 静默吞掉，不弹 toast（避免打扰 22:00 弹窗体验）
- 后端缓存策略: `fetch_date` 当日 1 次，跨日失效

---

## 5. 缓存策略（统一）

| 改动 | 缓存 key | TTL | 写表条件 |
|---|---|---|---|
| A 事件因子 | `event_factor_cache.trade_date = today` | 当日 1 次 | ifind 拉取成功 |
| B 基本面过滤 | **不缓存**（票级实时查，20 条/次，可控）| — | — |
| C 消息面 | `reflection_context_cache.fetch_date = today` | 当日 1 次 | ifind 拉取成功 |

**失败不写缓存**（与 brainstorm "失败就是失败" 一致）。

---

## 6. 错误处理（统一）

| 触发 | 行为 |
|---|---|
| A/B/C 任一 ifind 子调用超时（默认 8s） | 子调用抛 `IfindTimeout` → 改动点对应行为整体抛错 |
| ifind 鉴权失败 | 抛 `IfindUnavailable(reason='auth')` → 改动点整体抛错 |
| ifind 限流（HTTP 429） | 抛 `IfindUnavailable(reason='rate_limit')` → 改动点整体抛错 |
| A 失败 | screener 跑无事件因子版（4 因子），log WARNING |
| B 失败 | screener run 标 `fundamental_filter_status='failed'`，**不展示 Top N** |
| C 失败 | 前端静默吞错，不加消息面那一行 |

---

## 7. 测试覆盖

| 测试文件 | 改动 | 覆盖 |
|---|---|---|
| `test_event_factor_service.py`（新）| A | mock ifind，成功 / 失败 / 缓存命中 |
| `test_scoring.py`（扩）| A | `event_score` 单元测试 |
| `test_screener.py`（扩）| A + B | 评分公式叠加 / 基本面过滤失败 / 全踢出 |
| `test_reflection_context_service.py`（新）| C | mock ifind，成功 / 失败 / 缓存 |
| `conftest.py`（扩）| A/B/C | `mock_thsifind` fixture（monkeypatch thsifind 工具）|

---

## 8. 实施顺序

按依赖关系：

1. **A 先**（动 screener 评分公式，最重要）
2. **A → B**（B 依赖 screener 跑出 Top N）
3. **C 并行**（独立 UI 改动，可与 A/B 同期开发）

建议提交节奏：
- Commit 1: A 全部（event_factor_service + cache_repo + scoring + tests）
- Commit 2: B 全部（fundamentals + orm 扩列 + migration + tests）
- Commit 3: C 全部（reflection_context + UI + tests）

---

## 9. 文档更新

| 操作 | 文件 |
|---|---|
| 🆕 新增 | `docs/dev-log/ADR-0008-ifind-screener-reflection-optimization.md`（沿 ADR-0006/0007 风格：背景/决策/拒绝方案/数据模型/影响）|
| ✏️ 修改 | `docs/dev-log/decisions-index.md` 追加 ADR-0008 条目 |
| ✏️ 修改 | `docs/dev-log/runbook.md` 追加"ifind 故障排查"小节 |
| ✏️ 修改 | `docs/release-notes.md` 追加本次三项变更 |

---

## 10. 风险点

| 风险 | 缓解 |
|---|---|
| ifind 计费 / 限流 | 缓存策略（当日 1 次）+ 单子调用超时 8s |
| ifind 鉴权 / 配额用尽 | 失败 fail-fast，不阻塞主流程（除 B 外） |
| screener 加事件因子后**评分阈值变化** | 总分上限 155→170，下游按相对排序不受影响 |
| ReflectionCard 网络抖动影响 22:00 体验 | 前端静默吞错，行为降级 = 不显示该行 |
| 用户本地未提交改动（22 文件）冲突 | Review 阶段用户确认；如冲突以用户当前改动为准 |

---

## 11. 不做（YAGNI）

- ❌ ifind LLM 调用
- ❌ ifind 智能选股另起范式
- ❌ 实时盘中预警
- ❌ ifind 多账户
- ❌ ifind 自动调度（用户主动触发，不后台跑）
- ❌ 重写现有 screener 评分公式
- ❌ 改 LLM Provider 或 prompt 风格
- ❌ 把 ifind 接入 `data/unified.py`（行情源），新建独立 `app/data/ifind_*.py`
- ❌ 新增 ifind 缓存降级矩阵（部分字段缺失显示空态）

---

## 12. 待确认（review 时请确认）

1. **本地 22 个未提交改动**是否需要先 commit 再开始？建议先 stash 或 commit，本 spec 基于"最新未提交"现状设计
2. **改动 B 的"基本面兜底过滤"**默认 query 是否合适（`扣非ROE>0 PE<行业中位数 剔除ST`）？可调
3. **改动 A 事件因子权重** `SCREENER_EVENT_FACTOR_WEIGHT=15` 是否合适？占总分约 9%
4. **改动 C 是否需要**新增 `/api/reflection-context` 后端端点？还是直接让前端从 `lib/api` 调外部 ifind（**不推荐**，破坏分层）
5. **缓存策略**：A/C 用 SQL 表 vs 用进程内 LRU dict（参考现有 `app/services/event_bus.py` 风格）？spec 默认 SQL 表
6. **ADR 命名** ADR-0008 是否合适（接续 0006 screener、0007 watchlist）

---

> **下一步**: 等用户 review → 写 implementation plan → 进 writing-plans skill