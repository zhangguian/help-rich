# ADR-0007: 观察池(Watchlist)— 标选 + 周/月胜率

## 状态
已采纳(2026-08-09,v2.6.1)

## 背景

v2.6 上线盘后选股(screener)模块后,用户能从沪深 300 + 中证 500 池中筛选出 Top 20 候选。但**没有"跟进机制"**:用户看到候选后,要切回自选 tab 手动加,后续无法系统化跟踪"我标过的股后续表现如何"。

散户选股的核心闭环应该是:**发现 → 标记 → 跟踪 → 验证胜率 → 优化策略**。本模块补足"标记 → 跟踪 → 验证"三个环节。

## 决策

### 1. 数据模型 — 独立新表,不复用 watchlist

不复用现有 `watchlist` 表(`source='manual' / 'diagnosis'`),新建:
- `screener_watchlist` — 标选主表(UNIQUE stock_code,幂等标记)
- `screener_watchlist_daily` — 标选后逐日 K 线记录(UNIQUE watchlist_id + trade_date)

理由:
- 选股 vs 自选业务语义不同(标选是为了验证"该股后续涨跌",不是日常关注)
- 现有 `watchlist.is_favorite` 是标星,跟"标选观察"语义重叠会混乱
- 标选需要"标选日 + 逐日记录",现有 `watchlist` 表无这些字段,扩展会污染

### 2. 逐日记录 — 按需懒加载,不靠后台调度

用户**首次访问观察池**时:
- 拉 KlineCache 60 日 K 线
- 过滤 `trade_date >= marked_at`
- 每根算 `pct_from_marked = (close - marked_close) / marked_close`
- 批量 upsert 到 `screener_watchlist_daily`

不靠后台调度,因为:
- 后端已有 KlineCache(K 线数据已缓存,拉新数据 0 成本)
- 5~20 只股× 60 根 = 最多 1200 根,前端拉取<2s
- 后台调度要应对"加新表 + 新调度 + 新失败处理",复杂度陡增

### 3. 周/月分桶 + 胜率口径

| 维度 | 算法 |
|---|---|
| 周 | ISO 周(`YYYY-Www`,周一~周日)。8/10~8/16 为 W32 |
| 月 | 自然月(`YYYY-MM`) |
| 周/月聚合 | `(label, watchlist_id)` 取最新一条 daily record → 计算该 label 内:股数 / 平均涨跌 / hit 数 / miss 数 / hit_rate |

**胜率定义**:`pct_from_marked > 0` 算 hit;< 0 算 miss;= 0 不计。**未实现**:N 天后涨跌(传统回测);改用"逐日累计涨跌 vs 标记日"。

### 4. LLM 不参与 — 纯规则展示

胜率表纯规则计算,不调 LLM。理由:
- 用户已要求"取消降级机制"(v2.5.4 决策)
- 胜率数字是确定算法,LLM 无增值
- 降低 API 配额消耗

### 5. UI 设计 — 主页新 tab"⭐ 观察池"

- 主页顶部 tab 加新选项:`📈 选股` 后 + `⭐ 观察池` + `设置`
- 选股页 Top 卡片右上 ⭐ 按钮(点击 add/remove,乐观更新本地 UI)
- 观察池页布局:Header(总览)+ 周分桶表 + 月分桶表 + 表格内每行右侧 ✕ 取消
- 数据更新:观察池页"🔄 刷新每日走势"按钮,带 refresh=true 参数

### 6. 数据初始化

不需要(数据是用户即时产生的)。KlineCache 已有沪深 300 + 中证 500 的历史 K 线,直接复用。

## 影响

### 新增文件
- 后端 4 个:
  - `app/repositories/screener_repo.py`(追加 watchlist/daily 部分)
  - `app/services/screener_service.py`(追加 add_to_watchlist + refresh + compute_summary)
  - `app/api/screener.py`(追加 3 个端点)
  - `migrations/versions/i1d2e3f4g5h6_watchlist_tables.py`
  - `tests/test_screener_watchlist.py`(15 个)
- 前端 2 个:
  - `components/screener/WatchlistPanel.tsx`
  - `lib/screener.ts`(追加类型 + client)
- 文档 2 个:
  - `docs/dev-log/ADR-0007-screener-watchlist.md`(本文)
  - `docs/release-notes.md`(v2.6.1 章节)

### 修改文件
- `app/models/orm.py` — 加 2 个模型
- `app/api/screener.py` — `/screener/latest` picks 加 `is_watched`
- `frontend/src/app/page.tsx` — TabKey + TABS + 渲染分支 + aside 收起
- `frontend/src/components/screener/ScreenerPanel.tsx` — 加 ⭐ 按钮 + handleToggleWatch
- `frontend/src/lib/screener.ts` — ScreenerPick 加 isWatched 字段 + 新类型

### 不兼容变更
无。

## 风险与回退

| 风险 | 缓解 |
|---|---|
| K 线不足 60 日时 pct_from_marked 计算错 | `_iso_week_label` 过滤 `trade_date >= marked_at`,缺数据则该周股数少 |
| 用户频繁点 ⭐(误触)|乐观更新 + 后端幂等(已存在返 already_existed=true)|
| 标的退市 / 长期停牌 → 逐日记录永远无更新 | upsert_daily_records 按 trade_date 已成交日算,缺数据则跳过 |
| 5 只股 × 60 日 = 300 根,后续表大 | 每日新增最多 5 行(5 只股各 1 行);一年后 ≈ 1500 行,SQLite 无压力 |
| 标记日有 bug 导致所有 pct 错 | marked_close 优先用 KlineCache 标选日 close,失败用 QuoteService 兜底,全失败返 None(观察池仍记录但无涨跌) |
| TS exactOptionalPropertyTypes 与新 isWatched 不兼容 | 字段是 boolean 必需(非 optional),不受影响 |

## 后续路线

- v2.7:N 天后胜率(`_observe_view_outcome` 模式,可与现有 P1 view winrate 复用)
- v2.7:定时任务每天 16:00 自动 refresh(代替手动按钮)
- v2.8:行业分组胜率(按板块聚合)
- v3.0:组合回测(用户多个标的的虚拟组合)