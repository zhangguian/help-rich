# ADR-0006: 盘后选股(screener)模块设计

## 状态
已采纳(2026-08-09,v2.6)

## 背景

项目核心是单只股票的深度分析(indicators + AI 解读),但缺少"看一片"的工具。
散户最大痛点之一是"该买哪只" —— 当前用户**只能逐只翻看**,无法批量对比资金驱动信号。

## 决策

新增 `screener` 模块,核心要素:

| 项 | 选择 | 理由 |
|---|---|---|
| 候选池 | 沪深 300 + 中证 500 | 主流流动性好(约 800 只);排除 ST/北交所等边缘 |
| 选股哲学 | 资金驱动 | 散户最直观的"主力净流入 + 量比"信号 |
| 评分因子 | 主力净流入 + 量比 + 涨幅 + 连涨 + 板块强度 | 四维加权,满分 155 |
| 评分版本 | `SCREENER_SCORING_VERSION = "v1.0"` | 落 screener_runs.scoring_version,便于回溯 |
| 调度节奏 | 后台 15:30 工作日自动跑批 + 落库 | 不打扰用户 |
| LLM | 用户主动按按钮触发(幂等) | 不烧 API,失败不阻塞 |
| 数据源 | 复用现有 sector-fund-flow + KlineCache | 0 新探活,跟架构一致 |

### 评分公式(集中在 `app/core/config.py` 可调)

```
score = main_inflow_score(0..60)
      + volume_ratio_score(0..40)
      + momentum_score(0..30)
      + sector_strength_score(0..25)
      (max 155)
```

各因子边界(全部纯函数 `app/services/scoring.py`,便于单测):
- 主力净流入 ≥ 1 亿起 30 分;每多 0.5 亿 +5,3 亿封顶 60 分
- 量比 1.5/2.0/3.0 三档分别 +20/+10/+10,封顶 40 分
- 涨幅 3~7% 拿满 20 分;>7% 折半;温和 0~3% 一半;连涨 ≥2 天 +10
- 板块资金榜 Top5 得 15,Top6~20 得 8;同板块 ≥2 只入榜额外 +5

入库过滤:成交额 < 1 亿剔除;近 5 日跌幅 ≤ -15% 剔除(避雷);综合分 < 30 剔除。

### 拒绝的反方案

- ❌ **全市场 5000+ 扫描**:行情拉取 QPS / 后端压力太大;流动性差股干扰信号
- ❌ **自定义条件编辑器**:MVP 不做(产品决策 D11 — 4 个预设策略;自定义延后 v0.3)
- ❌ **筛选时自动调 LLM**:烧 API + 失败阻塞主流程;改为用户主动按钮
- ❌ **stale_cache 兜底**(参考本项目 v2.5.4 的取消 stale_cache 决策):本模块 LLM 失败 = 显示错误,让用户重试,不伪造

### 数据模型

新增 4 张表(`migrations/versions/h0c1d2e3f4g5_screener_tables.py`):
- `index_constituents` — 沪深 300 + 中证 500 静态表,季度更新
- `screener_runs` — 每日批次,UNIQUE(run_date)支持重跑覆盖
- `screener_picks` — Top N 候选股 + 各因子明细 + 触发规则 chip
- `screener_llm_picks` — 用户主动触发的 LLM 评选结果,UNIQUE(run_id)实现幂等

### 候选池初始化

`scripts/init_index_constituents.py` 提供两种策略:
- 一级(在线):东财 API 全量拉取(`fs=b:+000300`、`b:+000905`)
- 二级(兜底):内置 `_SEED_HS300 / _SEED_CS500`(~150 只)

用法:
```bash
python -m scripts.init_index_constituents                  # 在线 + 增量
python -m scripts.init_index_constituents --seed-only     # 仅种子
python -m scripts.init_index_constituents --force          # 清空重写
```

## 影响

### 新增文件
- 后端:
  - `app/services/scoring.py`(纯函数评分公式)
  - `app/services/screener_service.py`(跑批 + 调度)
  - `app/services/screener_llm_prompt.py`(LLM 评选 + 严格校验)
  - `app/repositories/screener_repo.py`(4 张表 CRUD)
  - `app/api/screener.py`(5 个端点)
  - `migrations/versions/h0c1d2e3f4g5_screener_tables.py`
  - `scripts/init_index_constituents.py`
  - `tests/test_scoring.py`(22 个)
  - `tests/test_screener.py`(17 个)
- 前端:
  - `src/lib/screener.ts`(API client + 类型)
  - `src/app/screener/page.tsx`(列表 + LLM 评选折叠)

### 修改文件
- `app/models/orm.py` — 加 4 个 ORM 模型
- `app/core/config.py` — 加 `SCREENER_*` 常量
- `app/main.py` — 注册 router + 启动调度器

### 不兼容变更
无。原有功能不受影响。

## 风险与回退

| 风险 | 缓解 |
|---|---|
| LLM 评选失败 / 返回非法 JSON | `_parse_llm_json` 已严格化(只接受纯 JSON 或 ```json```);失败落 `status=failed` + `error`,前端展示红字重试按钮 |
| 重复烧 LLM | `screener_llm_picks` UNIQUE(run_id) + 端点幂等检查;`?force=true` 才重跑 |
| 候选池过期 | `--force` 重写 + 跑批前 `pool_size=0` 警告 |
| 评分公式主观 | `scoring_version` 字段落库,便于回测比较 + AB |
| trigger-now 被生产误调 | 仅 `SCREENER_ALLOW_TRIGGER=1` 才允许(默认 403) |
| 跑批耗时过长 | 并发(quote 32 + kline 16 协程);800 只首次估计 30~60s,后续走缓存显著加速 |
| 主力净流入是板块代理(非个股真实主力) | 当前简化方案;后续加新浪个股资金字段探活(已记入 v2.7 路线) |

## 后续路线

- v2.7:个股资金流数据源探活 + 替换板块代理
- v2.8:回测接口 `GET /api/screener/backtest?days=90` 验证策略胜率
- v0.3:用户自定义选股条件编辑器(产品决策 D11 推迟)