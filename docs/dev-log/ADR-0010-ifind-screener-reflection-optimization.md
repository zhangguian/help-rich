# ADR-0010: iFinD 驱动现有模块优化（事件因子 / 基本面兜底 / 消息面提示）

## 状态：已采用（2026-09-22）

> **编号说明**: 本 ADR 编号 0010 而非 0008, 因为 pre-existing `decisions-index.md` L14 已占用 0008（"板块K线缓存用纯内存(非 Redis)", 实际未对应文件, 是历史遗留引用）。本 ADR 跳过该编号避免冲突。

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
1. screener 加事件因子加权(第 5 因子, 0/15 两档; 命中热门事件相关股 +15, 未命中 0)
2. screener Top N 末尾追加基本面兜底过滤(hard gate, 'passed'/'kicked'/NULL 三态)
3. ReflectionCard 22:00 加消息面提示行(失败静默)

## 拒绝方案
- ❌ ifind LLM 调用: thsifind 是数据接口, 不是 LLM
- ❌ ifind 智能选股另起范式: screener 已有评分体系
- ❌ 实时盘中预警: 盘后复盘场景, 不需要实时
- ❌ ifind 多账户: 个人单机工具
- ❌ ifind 自动调度: 用户主动触发, 不后台跑

## 数据模型
新增 2 张表 + 1 个 screener_picks 扩列迁移 = **共 3 个 Alembic 迁移**:
- event_factor_cache(trade_date PK, event_keywords_json, stock_codes_json, fetched_at, ifind_calls, created_at, updated_at)
- reflection_context_cache(fetch_date PK, context_json, fetched_at, ifind_calls, created_at, updated_at)
- screener_picks 表新增列 fundamental_filter_status('passed'/'kicked'/NULL)

## 影响
跨 17 commits: 新增 13 个文件, 修改 11 个文件, 新增 1 个 Alembic 迁移 + 2 个 screener_picks 扩列 + reflection_context_cache 迁移。
screener 总分上限 155 → 170; 失败语义: A/C 静默不阻断, B 失败不展示 Top N。
完整设计: docs/superpowers/specs/2026-09-22-ifind-screener-reflection-optimization-design.md