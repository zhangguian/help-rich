# 场内 ETF 支持(实施规格 v1.0)

> **状态**:✅ 已实施(2026-10-25)
> **范围**:场内 ETF / 场内 LOF —— 品种识别 + 交易规则适配 + 展示层
> **替换**:本文取代 v0.6《ETF 改造方案(RFC v0.6)》—— 那份是未评审、未实施的设计稿,
> 且与现状漂移(表文件名、表内容、降级语义、落点位置均不同)。差异清单见 §8。

---

## 1. 背景与目标

场内 ETF 在本项目里**数据通路一直是通的**(行情 / 日 K / 分时全部实测可用),
真正缺的是两件事:

| 缺什么 | 后果 |
|---|---|
| **看不出品种** | 自选 / 持仓列表里 ETF 与股票长得一样,用户不知道它跟踪什么指数 |
| **算不对** | 拿股票规则算 ETF:印花税/过户费照收、T+1 提示错、涨跌停误判、正T 上限算小 |

第 2 条比第 1 条严重 —— **结论是事实性错误**,不只是不好看。

### 目标(验收口径)

| 目标 | 验收方式 |
|---|---|
| 品种可辨 | 自选 / 持仓 / 个股页显示 `📊 ETF` 徽章(跨境/商品带 `T+0` 小标) |
| 跟踪指数可见 | 分析页「机械信号」卡显示「跟踪 {指数}」 |
| 费用按品种 | ETF 免印花税、免过户费;佣金沿用用户配置 |
| 回转规则按品种 | T+0 品种的卖出腿可用当日买入份额;正T 上限只受资金约束 |
| 涨跌停不误判 | ETF 无涨跌停 → 不再说「涨停」,改说涨幅已达 X% |
| AI 不说股票的话 | ETF 的风险清单换成折溢价 / 跟踪误差 / 汇率 / T+0 规则差异 |
| 缺数据不装懂 | 表外 ETF 保守按 T+1,且判定层明说「未在品种表内」 |

---

## 2. 范围

### 2.1 本期做

- **品种识别**:境内股票 ETF + 跨境 ETF(QDII)+ 黄金/商品(含商品期货 ETF)+ 场内 LOF
- **交易规则适配**:费用 / T+0-T+1 / 无涨跌停 / AI 提示词
- **展示层**:品种徽章 + 跟踪指数 chip

### 2.2 本期不做(字段已预留)

| 项 | 状态 | 原因 |
|---|---|---|
| 债券 ETF / 货币 ETF | 类别字段(`bond`/`money`)已留,**未启用条目** | 这两类的 T+0 / 费用规则与本期 ETF 不同,不能顺手带过 |
| 场外基金(001511 等) | 不支持 | 需要 `.OF` 后缀与另一套数据源 |
| ETF 折溢价 / 规模 / 费率 | 不支持 | 需东财基金详情接口,单独排期 |
| 三线叠加的 ETF 指数对比线 | 明确禁用 | 缺 `index_code → secid` 映射,给不出真实数据就别画 |

---

## 3. 总体结构

```
backend/app/data/etf_instruments.json   # 品种表(静态,46 项,零数据库迁移)
backend/app/core/instrument.py           # 判定层:resolve_instrument / fees_for_instrument / degraded_note
        │
        ├─ core/cost_engine.py           # TradeFees.etf_variant():印花税/过户费置 0
        ├─ services/trade_review_service.py  # T+0/T+1 文案 + 正T 上限公式分流
        ├─ services/decision_service.py  # 追高文案按品种分流
        ├─ services/industry_service.py  # ETF 分支提前 + resolve_industry_sync(纯本地)
        ├─ modules/analysis/prompts.py   # 风险清单 / PM 严重风险按品种
        └─ api/calculator.py / annual_report_service.py  # 按品种选费用档

frontend/src/lib/etfInstruments.json    # 前端副本(由后端表生成,后端测试逐项比对防漂移)
frontend/src/lib/instrument.ts           # resolveInstrument / isEtf / instrumentBadgeTitle
frontend/src/components/ui/EtfBadge.tsx  # 品种徽章组件
```

**依赖方向**:`core/instrument.py` 只依赖 `core/cost_engine.py`(core→core 合法),
不依赖任何业务层 —— 架构守卫 `test_core_does_not_depend_on_business_layers` 通过。

---

## 4. 品种表与判定

### 4.1 表结构

`backend/app/data/etf_instruments.json`

```json
{
  "version": "2026-10-25",
  "source": "代码与场内简称用新浪行情接口逐只核对;跟踪指数用天天基金 F10 核对",
  "categories": { "broad": "宽基", "industry": "行业", "qdii": "QDII",
                  "commodity": "商品", "bond": "债券", "money": "货币" },
  "items": [
    {"code": "513100.SH", "name": "纳指ETF国泰", "index": "纳斯达克 100",
     "category": "qdii", "t0": true},
    {"code": "162411.SZ", "name": "华宝油气", "index": "标普石油天然气上游",
     "category": "commodity", "t0": true, "form": "lof"}
  ]
}
```

| 字段 | 含义 |
|---|---|
| `code` | 带市场后缀的规范代码 |
| `name` | 场内简称(新浪行情口径,与应用里显示的一致) |
| `index` | 跟踪指数 / 业绩比较基准 |
| `category` | 宽基 / 行业 / QDII / 商品 / 债券 / 货币 |
| `t0` | 是否当日可回转(T+0) |
| `form` | `etf`(默认)/ `lof`(场内上市开放式基金) |

**46 项分布**:宽基 6 / 行业 23 / QDII 10 / 商品 7;其中 `form=lof` 5 项、`t0=true` 17 项。

### 4.2 判定顺序(`core/instrument.py::resolve_instrument`)

1. **命中表** → `kind=etf`、带类别 / 跟踪指数 / T+0 / 形态
2. **表外但符合 ETF 格式**(`5xxxxx.SH` / `1xxxxx.SZ`)→ `kind=etf`、`known=False`、**保守按 T+1**
3. 其余 → `kind=stock`

> **为什么表外要保守**:513100(纳指,跨境)与 510300(沪深 300,境内)都是 51 开头,
> 代码前缀分不开。无据不判 T+0 —— 判错 T+0 会直接算错正T 上限。
> 表外 ETF 必须显式降级(§4.3),不静默、不假装已知。

### 4.3 降级语义

| 情况 | 判定层行为 | 文案 |
|---|---|---|
| 表内 ETF | 正常 | —— |
| 表外 ETF | 按 T+1 / 股票费率算,`degraded` 里明说 | 「该 ETF 未在品种表内,已按保守口径(T+1 / 股票费率)计算,交易规则可能有偏差」 |
| 表缺失 / 损坏 | 不抛错,空表 + 保守路径 + `logger.warning` | 同上 |
| 表项缺 `t0` | 视为 `false`(保守) | —— |

### 4.4 前后端两份表防漂移

前端徽章要出现在自选 / 持仓列表 —— 那些接口不返回品种属性 → 前端必须本地能查表。
前端副本 `frontend/src/lib/etfInstruments.json` **由后端表生成**,并由后端测试逐项比对:

```
backend/tests/test_instrument.py::TestFrontendTableConsistency
  ├─ test_frontend_copy_has_same_code_set   代码集合一致
  ├─ test_frontend_copy_fields_match         name/index/category/t0/form 逐项一致
  └─ test_frontend_copy_categories_match     类别中文标签一致
```

改后端表必须重跑生成脚本,否则 CI 红。已实测:故意把前端副本的 `category` 改错 → 测试立即失败并指出
「510050.SH 的 category 不一致:后端='broad' 前端='BROKEN'」。

---

## 5. 规则层(G1–G5)

### G1 费用:ETF 免印花税、免过户费

- `core/cost_engine.py` 新增 `TradeFees.etf_variant(base)`:印花税 / 过户费置 0,佣金沿用用户配置
- `calculate_after_transaction` **签名不变**(费用由调用方传入)
- 落点只有两处:**试算**(`api/calculator.py`)与**年报**(`annual_report_service.py`,逐笔按品种选档)
- **判定层费用仍是 `None`** —— 持仓成本链本就不含费(D3 既有口径不变),`cost_settings` 表与 API 契约零改动

实测:卖出 1000 @ 20.000 → 股票档 fee **15.20** / ETF 档 fee **5.00**(佣金 5 + 印花税 10 + 过户费 0.2)

### G2 T+0 / T+1 回转规则

- `trade_review_service` 新增 `T0_NOTE`;`_build_t_directions(..., t0=False)`
- 前置条件拆成 `common_block`(通用)与 `position_block`(仓位相关),按品种分流
- **T+0 品种不再卡「缺底仓比例」**(T+1 仍卡 —— 卖腿要预留老底仓)
- 提示文案分流:股票「A 股 T+1:当天买入的股票当天不能卖出…」/
  ETF「该品种为 T+0(当日可回转):当天买入的份额当天就能卖出…(具体以交易软件显示的品种属性为准)」

### G3 正T 上限公式

| 品种 | 正T(先买后卖)上限 | 反T(先卖后买)上限 |
|---|---|---|
| T+1 | `min(可动T仓 M, 资金可买股数)` | 受 M 约束 |
| **T+0** | **只受资金约束** `floor(可用资金 ÷ 买价)` | 仍受 M 约束(不能把仓位卖光) |

`_floor_lot`(100 份整手)不变。

实测(持股 1000 → 可动 T 仓 500,可用资金 20000):

| 标的 | 品种 | 正T 上限 | 依据 |
|---|---|---|---|
| 513120.SH 港股创新药 | T+0 | **16,500 股**(≈¥19,899) | 只受资金约束 |
| 002185.SZ 华天科技 | T+1 | **500 股**(≈¥7,645) | 受可动 T 仓约束 |

### G4 涨跌停文案分流

`NEAR_LIMIT_UP_PCT = 9.5` **不分档**(9.5% 对 ETF 已是极端涨幅),只改文案:

- 股票:「已接近涨停(9.5%)」
- ETF:「当日涨幅已达 X%,不追高(ETF 无涨跌停限制,涨幅可以更大)」

一字板判定保留(ETF 也会一字)。

### G5 AI 提示词按品种

- `modules/analysis/prompts.py`:`build_risk_prompt` / `build_pm_prompt` 加 `instrument_kind` 参数
- ETF 风险清单换成:**折溢价 / 跟踪误差 / 流动性 / 汇率 / T+0 规则差异**
- PM 严重风险换成:**跟踪指数大幅下跌 / 折溢价过大**
- 判定层纯函数、零 IO、零 LLM;LLM 只翻译不计算;缺数据 → `None` + degraded,绝不编数字

---

## 6. 展示层

### 6.1 品种徽章 `components/ui/EtfBadge.tsx`

| 形态 | 样式 |
|---|---|
| 表内 ETF | 实线琥珀徽章 `bg-warn-bg` + `text-warn` + `border-warn/30` |
| 表内 T+0 品种 | 徽章内再加深底小块 `T+0`(`bg-warn/30`) |
| 表外 ETF | 虚线灰徽章(`border-dashed` + `text-text-ter`) |
| 股票 | 不渲染 |

hover 说明:形态(场内 ETF / 场内 LOF)· 类别 · 跟踪指数 · 是否 T+0。

> **配色语义**:琥珀(warn 家族)表示「这是另一类标的」,刻意避开
> accent(青 = 选中/焦点)与 danger(红 = 判定结论)—— 徽章是**品种分类**,不是判定结论。

### 6.2 落点清单

| 位置 | 组件 |
|---|---|
| 自选 · 盯盘侧栏(rail) | `components/watch/WatchList.tsx` |
| 自选 · 大卡片 | `components/watch/WatchList.tsx` |
| 持仓摘要表(首页) | `components/positions/PositionSummaryTable.tsx` |
| 持仓卡片列表(/positions) | `components/positions/PositionsList.tsx` |
| 个股详情页标题 | `app/(app)/stock/[code]/page.tsx` |

### 6.3 跟踪指数 chip

落在**机械信号卡(SignalPanel)标题行下方**(现状 AnalysisPanel 没有行业 chip 位置,SignalPanel 是唯一稳定落点):

- 股票 → 行业名(baostock 口径),灰白 chip
- ETF → 「跟踪 {指数}」,琥珀 chip + 副注「场内 ETF · QDII」

### 6.4 ETF 在「操作决策」卡里的呈现(v0.10 增补)

决策卡的「操作建议」区(v0.10)有两个维度对 ETF 特别有意义:

| 维度 | ETF 的差异 | 呈现 |
|---|---|---|
| **品种规则** `instrument_rule` | 无涨跌幅限制(涨到 9.5% 不是涨停);免印花税、免过户费(只收佣金);跨境/黄金类 **T+0 当日可回转** | 折叠区「更多维度」里一行;另在「别动」里对 ETF 改说「不追高」而不是「涨停」 |
| **费用影响 / 网格** `cost_effect` · `grid_plan` | 往返费率 **0.05%**(股票 0.102%)→ 同样的网格,ETF 每格净收益更高 | 网格块里给出往返费率;震荡时 ETF 更适合网格 |

**为什么 ETF 与网格天然咬合**:网格每格赚的是「一档价差 − 往返费用」,
ETF 免印花税使这层摩擦成本减半;叠加 T+0 当日可回转,同一只 ETF 既能日内做 T,
也能挂网格 —— 但**二者互斥,择一执行**(决策卡会显式提示)。

**边界**:网格建议只给区间 / 格数 / 资金需求 / 单格净收益 / 失效条件,
**不承诺收益、不自动下单**(设计文档 §10.4 口径:胜率型概率提示,收益型无效)。

---

## 7. 接口与行业归属

### 7.1 行业归属兜底顺序调整

```
resolve_industry(带网络):baostock → ETF 本地表 → 新浪排行反查 → 降级
resolve_industry_sync(纯本地):baostock → ETF 本地表
```

**为什么 ETF 提前**:命中 ETF 本地表是纯本地判定,而新浪要打网络。
先查 ETF,否则每个 ETF 请求都要白等一次网络超时。股票路径完全不受影响。

### 7.2 analysis 端点新增三字段

`GET /api/stock/{code}/analysis` 增加(缓存命中与未命中两条路径都注入):

| 字段 | 股票 | ETF |
|---|---|---|
| `industry` | 行业名 | 「跟踪 {指数}」 |
| `industry_source` | `baostock` | `etf_index` |
| `industry_note` | `null` | 「场内 ETF · {类别}」 |

实测:`513120.SH` → `{"industry":"跟踪中证香港创新药","source":"etf_index","note":"场内 ETF · QDII"}`;
`002185.SZ` → `{"industry":"C39计算机、通信和其他电子设备制造业","source":"baostock","note":null}`。

### 7.3 `GET /api/stock/{code}/industry`

返回 `{code, industry, source, note}`;`source` 取值 `baostock` / `etf_index` / `sina`。
表外 ETF → `industry: null`(不编造)。

---

## 8. 与 v0.6 原稿的差异

| 原稿(v0.6) | 实际实施 | 原因 |
|---|---|---|
| 表文件 `etf_index.json` | `etf_instruments.json` | 表里不止指数,还有类别 / T+0 / 形态 → 叫「品种表」更准 |
| ~40 只,含债券 / 货币 ETF 条目 | 46 项;债券 / 货币类别字段预留但**未启用条目** | 这两类的 T+0 与费用规则不同,不能顺手带过 |
| `resolve_industry` 顺序 baostock→新浪→ETF→降级 | baostock→**ETF**→新浪→降级 | ETF 是本地表判定,新浪要打网络;先查 ETF 省一次超时 |
| 降级返回 `source="degrade"` | 降级是 `industry=null`(+ note) | 现状实现就是 `None`,不是 `"degrade"` 字符串 |
| 跟踪指数显示在 AnalysisPanel | 落在 **SignalPanel**(机械信号卡) | 现状 AnalysisPanel 没有行业 chip 的位置 |
| 只解决「看得见」 | **新增规则层 G1–G5** | 原稿没解决「算得对」—— 用股票规则算 ETF,结论是事实性错误 |
| 无 LOF 概念 | 新增 `form=lof` | 场内 LOF 规则与 ETF 一致但不是 ETF,文案别混为一谈 |

---

## 9. 测试与实测记录

### 9.1 自动测试

| 文件 | 条数 |
|---|---|
| `tests/test_instrument.py`(新增) | 24(判定 7 + 降级 3 + 费用 3 + 表完整性 5 + 前后端一致性 3 + 表缺失/损坏 3) |
| `tests/test_trade_review_service.py` | +12(共 76;T+0 上限 / 反T 约束 / 文案 / 降级) |
| `tests/test_industry_service.py` | +14(共 20;ETF 兜底 / 不打新浪 / sync 版) |
| `tests/test_calculator_api.py` | +5(共 24;股票档 15.20 / ETF 档 5.00 / 表外仍走 ETF 档) |
| `tests/test_decision_service.py` | +1(共 33;股票说涨停 / ETF 不说但仍提醒不追高) |

全量:**1492 → 1548 passed(新增 56 条),零红**(11m51s)。

### 9.2 真机实测(tabbit / Playwright)

| 场景 | 结果 |
|---|---|
| 自选 rail 9 只 ETF 徽章 | 全部正确:琥珀实线 + `T+0` 深底小块(`rgba(245,165,36,.3)`)+ 跟踪指数准确 + LOF 显示「场内 LOF」 |
| 持仓卡片徽章 | `513120.SH` 行显示 `📊 ETF T+0` ✓ |
| 个股详情页 | 标题徽章 + 行业 chip「跟踪中证香港创新药」+ 副注「场内 ETF · QDII」 ✓ |
| 计算器 T 卡 T+0 | 513120:正T 上限 16,500 股(资金约束),前提写明「T+0 品种,卖出腿可用当日买入的份额,无需预留老底仓」 |
| 计算器 T 卡 T+1 | 002185:正T 上限 500 股(可动 T 仓约束),前提写明「需有老底仓承接卖腿」 |
| console 错误 | 0 |

实测用临时持仓 + 账户资金 20,000,**测完已清理**(持仓删除 204、现金恢复 `null`),
用户真实持仓与自选未被改动。

---

## 10. 风险与已知边界

| 边界 | 说明 |
|---|---|
| 表外 ETF 一律按 T+1 | 跨境 / 商品 ETF 实际 T+0 → 保守处理会**低估**正T 上限。这是刻意的:宁可少算,不可算错 |
| 表是手工维护 | 新增品种要:① 改后端表 ② 重跑生成脚本 ③ 跑 `test_instrument.py` |
| 跟踪指数是「展示名」 | 用跟踪指数名的常见简称;业绩比较基准与跟踪标的不同的(如混合型 LOF)按主口径记 |
| 债券 / 货币 ETF | 类别已留,条目未启用 |
| 折溢价 / 规模 / 费率 | 未接数据源,界面上不出现 |

---

## 11. 后续计划

| 项 | 优先级 | 说明 |
|---|---|---|
| 品种表增量同步脚本 | 中 | 从天天基金 F10 拉「跟踪标的 / 基金类型」自动补条目 |
| 表外 ETF 的 T+0 判定 | 中 | 需要更细的代码段 / 基金属性数据源,当前只能保守 |
| ETF 折溢价 | 低 | 东财基金详情接口 |
| 债券 / 货币 ETF | 低 | 规则另需确认,别顺手带过 |
| 场外基金 | 低 | `.OF` 后缀 + 另一套数据源 |

---

## 附录 A:关键决策记录

| # | 决策 | 依据 |
|---|---|---|
| D29 | 品种规则用静态 JSON 表(零数据库迁移) | 品种属性是**低频变化**的静态事实;迁移表 + 同步任务的成本不划算 |
| D30 | 表外 ETF 保守按 T+1,且判定层必须明说「未在品种表内」 | 无据不判 T+0;「不知道」和「按保守口径」是两件事 |
| D31 | T+0 正T 上限只受资金约束;反T 两类都受 M 约束 | T+0 卖出腿可用当日买入份额;反T 不能把仓位卖光 |
| D32 | T+0 品种不卡「缺底仓比例」 | T+1 卖腿要预留老底仓,T+0 不需要 |
| D33 | 费用适配只落试算与年报;判定层费用仍 `None` | 持仓成本链本就不含费;`cost_settings` 表与 API 契约零改动 |
| D34 | 涨跌停阈值不分档,只改文案 | 9.5% 对 ETF 已是极端涨幅,分档反而更啰嗦 |
| D35 | `resolve_industry` 把 ETF 分支提到新浪之前 | 否则每个 ETF 请求都白等一次网络超时 |
| D36 | analysis 用纯本地 `resolve_industry_sync` 注入行业 | 零网络开销;缓存命中与未命中都注入 |
| D37 | 前端持有品种表副本 + 后端测试逐项比对 | 徽章要出现在不返回品种属性的列表接口里;比对防漂移 |
| D38 | 修前端 `stockCode.ts` 缺失的 `['5','SH']` 前缀 | 既有 bug:认不出沪市 ETF,前后端市场推断不一致 |
| D39 | 行业 chip 落在 SignalPanel 标题行下方 | 现状 AnalysisPanel 没有行业 chip 位置 |
| D40 | 徽章 amber;T+0 为徽章内深底小块;表外虚线灰 | 用户拍板(视觉稿 `docs/design/preview/etf-instrument-preview.html`) |
