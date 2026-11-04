# API 契约文档:买股工具室

**文档版本**:v2.1
**最后更新**:2026-08-01
**对应代码版本**:v0.1.0(MVP)
**对应后端架构**:`backend-architecture.md` v2.1

**Base URL**:`http://localhost:8000`
**API 前缀**:`/api`
**鉴权**:MVP 无鉴权(单机自用)
**数据格式**:JSON,UTF-8

---

## 1. 端点总览

| 方法 | 路径 | 模块 | 说明 |
|---|---|---|---|
| GET | /health | 系统 | 健康检查 |
| GET | /positions | 持仓 | 持仓列表(含今日盈亏) |
| GET | /quotes/{code} | 行情 | 单只实时行情(P3.5 新增) |
| GET | /quotes | 行情 | 批量实时行情,最多 50 只(P3.5 新增) |
| GET | /transactions | 流水 | 流水列表 |
| POST | /transactions | 流水 | 录入交易 |
| PATCH | /transactions/{id} | 流水 | 修改 |
| DELETE | /transactions/{id} | 流水 | 删除 |
| POST | /calculator | 计算器 | 计算新成本 + 21 档 |
| POST | /calculator/review | 计算器 | 交易复核(做 T 方向 / 上限,按品种分流) |
| GET | /stock/{code}/analysis | 个股分析 | 技术指标 + AI 解读 + 行业标签 |
| GET | /stock/{code}/decision | 个股分析 | 确定性决策卡(零 LLM)+ 操作建议六格 + 网格建议 |
| GET | /stock/{code}/decision-advice | 个股分析 | 操作建议白话(按钮触发,LLM 失败退回规则文案) |
| GET | /stock/{code}/industry | 个股分析 | 行业归属(ETF 返回跟踪指数) |
| POST | /diagnose/{trade_id} | 诊断 | 触发评分 + 评语 |
| POST | /diagnose/backfill | 诊断 | 补评 / 全量重算(force=true) |
| GET | /diagnose/{trade_id} | 诊断 | 获取评分(轮询降级) |
| POST | /diagnose/{trade_id}/regenerate | 诊断 | A/B 用其他模型重新生成 |
| GET | /stop-losses | 止损 | 止损列表 |
| POST | /stop-losses | 止损 | 设置 / 更新止损 |
| DELETE | /stop-losses/{code} | 止损 | 删除止损 |
| POST | /stop-losses/{code}/triggered | 止损 | 标记触发(幂等) |
| GET | /annual-report/{year} | 年账单 | 年度账单 |
| GET | /watchlist | 自选股 | 自选股列表 |
| POST | /watchlist | 自选股 | 加入 |
| DELETE | /watchlist/{code} | 自选股 | 移除 |
| GET | /events/sse | SSE | 诊断结果推送 |
| GET | /llm/providers | LLM | 可用 provider 列表 |
| GET | /llm/settings | LLM | 当前激活 provider |
| POST | /llm/settings | LLM | 切换 provider |
| GET | /llm/keys | LLM | 3 Provider Key 配置状态 |
| PUT | /llm/keys | LLM | 更新 Key |
| POST | /llm/test | LLM | 测试 Key 连接 |
| POST | /screenshot/upload | 截图 | 上传 + 异步识别 |
| GET | /screenshot/pending | 截图 | 待确认列表 |
| POST | /screenshot/{id}/confirm | 截图 | 用户确认入库 |
| POST | /screenshot/{id}/reject | 截图 | 取消 |
| POST | /screenshot/parse-paste | 截图 | 降级路径解析粘贴 JSON |

---

## 2. 健康检查

### GET /api/health
**目的**:检测后端是否存活

**响应 200**:
```json
{ "status": "ok" }
```

---

## 2.5 行情(P3.5 新增)

### 2.5.1 GET /api/quotes/{code}

**目的**:获取单只实时行情(新浪主 + 腾讯备 + 5 分钟缓存)

**请求参数**:
| 参数 | 类型 | 说明 |
|---|---|---|
| code | str(path) | `600519.SH` / `000001.SZ` / `830799.BJ` |

**响应 200**:
```json
{
  "code": "600519.SH",
  "name": "贵州茅台",
  "current_price": "1350.600",
  "prev_close": "1361.760",
  "open": "1330.030",
  "high": "1355.720",
  "low": "1325.770",
  "change": "-11.160",
  "change_pct": -0.82,
  "volume": 5512752,
  "amount": "7373462605.000",
  "timestamp": "2026-08-01T14:03:52",
  "turnover_pct": null,
  "pe": null,
  "pb": null
}
```

**错误码**:
| code | HTTP | 触发条件 |
|---|---|---|
| — | 422 | 代码格式错误(需 6 位数字 + .SH/.SZ/.BJ) |
| — | 503 | 行情源不可用(新浪 + 腾讯都失败) |

### 2.5.2 GET /api/quotes?codes=600519.SH,000001.SZ

**目的**:批量获取行情,最多 50 只,返回数组。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| codes | str | 是 | 逗号分隔,最多 200 只 |
| fresh | bool | 否 | `true` = **跳过 5 分钟缓存**直取数据源(盯盘热路径,ADR-0006) |

**错误码**:同上(422 含具体非法代码)。

### 2.5.3 GET /api/quotes/stream(SSE,2026-10-29 新增)

**目的**:盘中行情推送。服务端单例轮询器(盘中 2s 一轮)拉「自选 ∪ 持仓」,
经事件总线广播,本端点把增量推给前端 —— 端到端 ≤3s(3 秒快照档 / Level-1,
**不是逐笔 Tick**,见 ADR-0006)。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| codes | str | 否 | 逗号分隔;不传 = 推全部 watchlist |

**响应**:`text/event-stream`,每帧形如 `data: {json}\n\n`

| 帧 | 时机 | payload |
|---|---|---|
| `quote_snapshot` | 首帧 | `{event, quotes[], updated_at, stale, source, last_error}` |
| `quote_update` | 每轮轮询后 | `{event, quotes[], updated_at, stale, source}` |
| `:heartbeat` | 30s 无数据 | 注释行,保活 |

**失败语义**:行情源不可用 → 轮询器保留上一轮快照并置 `stale=true`,
前端据此提示"数据可能滞后";**不会**收到编造的价格。

**降级(可逆)**:前端 SSE 连续失败 3 次 → 退回 `GET /api/quotes?codes=...&fresh=true` 轮询(3s)。

降级**不是单向的**:
- 降级时前端**不关闭** EventSource —— 浏览器自己按 ~3s 重连,后端一恢复就重新收到帧
  → 停掉 REST 轮询 + 清掉降级标记 → 自动回切 SSE;
- 页面**刷新后照样建立 SSE**(降级标记只决定"要不要同时开 REST 兜底",不决定"要不要连流"),
  否则标记一旦落下就再也回不到 SSE 模式(除非清站点数据)。

> 验收实测(2026-10-29):SSE 被断开后前端 3 次失败即切 REST 轮询(每 3s,`fresh=true` 跳过 5 分钟缓存);
> 后端恢复后 1.7s 内自动回切 SSE 且轮询停止。

### 2.5.4 盘中信号(2026-10-29 新增,ADR-0007)

对**持仓股**的四类盘中事件做检测,命中后**由后端直发 Windows 桌面通知**
(浏览器关着也能收到)。判定口径复用决策引擎的数值价位,与决策卡同源。

#### GET /api/signals/config

**目的**:读当前配置 + 运行时快照(当前生效的触发价 / 「今日不适合做T」的原文原因)。

**响应 200**:
```json
{
  "config": {
    "enabled": true,
    "velocity_window_sec": 60,
    "velocity_pct": 1.5,
    "breakout_up_pct": 5.0,
    "breakout_down_pct": -5.0,
    "enable_velocity": true,
    "enable_breakout": true,
    "enable_t_point": true,
    "enable_buy_point": true,
    "cooldown_sec": 600,
    "daily_limit": 5,
    "channels": ["desktop"]
  },
  "runtime": {
    "levels_updated_at": "2026-10-29T03:10:00",
    "codes": ["002185.SZ"],
    "levels": {
      "002185.SZ": [
        {"kind": "t_sell_point", "level": 12.5, "label": "T 卖出点",
         "condition": "上冲到 12.50", "basis": ""}
      ]
    },
    "notes": {"002185.SZ": ["t_plan: 今日振幅不足,不适合做T"]}
  }
}
```

`notes` 里的内容是**决策引擎自己给的原因原文** —— 不适合时**不产出任何价位**
(不替用户编一个触发价)。

#### PATCH /api/signals/config

**目的**:改阈值 / 开关 / 渠道(落库)。**只传要改的字段**(全字段可选)。

**请求体**(示例):
```json
{"velocity_pct": 2.0, "enable_breakout": false, "channels": ["desktop", "dingtalk"]}
```

**响应 200**:`{"config": { ...同 GET... }}`

**校验**:窗口 5~3600 秒;急速幅度 0~20%;涨幅突破 0~50%;跌幅突破 -50~0;
冷却 0~86400 秒;日限流 1~100。越界 → **422**。

#### GET /api/signals

**目的**:最近的信号流水(「为什么推了这条 / 为什么没推」)。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| stock_code | str | 否 | 按代码过滤 |
| limit | int | 否 | 最多返回条数(1~500,默认 50) |

**响应 200**:
```json
{
  "items": [
    {
      "id": 12, "stock_code": "002185.SZ", "stock_name": "华天科技",
      "kind": "t_sell_point", "level": 12.5, "value": 12.52,
      "title": "T 卖出点 · 002185.SZ", "body": "...",
      "fingerprint": "t_sell_point:002185.SZ:1250",
      "notified": true, "error": null,
      "created_at": "2026-10-29T03:12:00"
    }
  ]
}
```

`kind` 取值:`velocity_up` / `velocity_down` / `breakout_up` / `breakout_down` /
`t_sell_point` / `t_buyback_point` / `grid_sell_point` / `buy_point`。

`notified=false` 表示**没有推出去**:被冷却/日限流(见 `error`)或渠道发送失败。
**桌面通知由后端弹** —— 前端不调 `new Notification`。

#### GET /api/signals/stream(SSE)

**目的**:盘中信号实时推送。

**响应**:`text/event-stream`,每帧形如 `data: {json}\n\n`

| 帧 | 时机 | payload |
|---|---|---|
| `signal_snapshot` | 首帧 | `{event, levels_updated_at, codes[], levels{}, notes{}}` |
| `signal_fired` | 命中信号且推送成功 | `{event, signal: {id, kind, stock_code, stock_name, level, value, title, body}}` |
| `:heartbeat` | 30s 无数据 | 注释行,保活 |

**降级(可逆)**:前端连续失败 3 次 → 退回 `GET /api/signals` 拉流水(5s);
降级期间**不关闭** EventSource,后端恢复后自动回切 SSE(与 `/api/quotes/stream` 同款)。

#### POST /api/signals/test

**目的**:真弹一条桌面通知(验通道是否通)。

**响应 200**:`{"ok": true, "detail": "OK:BALLOON"}`
(`detail` 的 `OK:BALLOON` = 走托盘气泡兜底;`OK:<AUMID>` = 走了 WinRT 通知中心 Toast)

**失败**:非 Windows → `ok=false` + `detail` 说明;两条路径都失败 → `ok=false`。

---

## 3. 交易流水

### 3.1 GET /api/transactions

**目的**:获取流水列表(支持分页 / 筛选)

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| stock_code | str | 否 | 按股票筛选 |
| start_date | date | 否 | 起始日期(包含) |
| end_date | date | 否 | 结束日期(包含) |
| limit | int | 否 | 默认 50,最大 200 |
| offset | int | 否 | 默认 0 |

**响应 200**:
```json
{
  "items": [
    {
      "id": 1,
      "stock_code": "000001",
      "stock_name": "平安银行",
      "action": "buy",
      "shares": 500,
      "price": "10.500",
      "trade_date": "2026-07-30",
      "trade_time": "14:38:00",
      "note": null,
      "score": 72,
      "created_at": "2026-07-30T15:30:00"
    }
  ],
  "total": 1
}
```

**业务说明**:`price` 是字符串(精度保护),前端 `decimalFormat` 显示
**关联**:触发诊断后,`score` 字段填充
**`trade_time`**:时间节点(HH:MM:SS);`null` = **未知**(存量流水 / 用户留空 / 截图导入),
不编造时间。同一交易日的多笔流水按 `(trade_date, trade_time, id)` 排序 →
时间点参与成本链重放(时间未知的排在同日有时间的流水之前)。

### 3.2 POST /api/transactions

**目的**:录入一笔交易

**请求体**:
| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| stock_code | str | 是 | 6 位数字 | 股票代码 |
| action | enum | 是 | buy / sell | 交易方向 |
| shares | int | 是 | > 0 | 交易股数(整百) |
| price | Decimal | 是 | > 0,3 位小数 | 交易价格 |
| trade_date | date | 是 | YYYY-MM-DD | 交易日期 |
| trade_time | str | 否 | HH:MM / HH:MM:SS | 时间节点;留空 = 未知(不编造) |
| note | str | 否 | ≤ 200 字 | 备注 |

**示例**:
```json
{
  "stock_code": "000001",
  "action": "buy",
  "shares": 500,
  "price": "10.500",
  "trade_date": "2026-07-30",
  "trade_time": "14:38",
  "note": "看好银行板块"
}
```

**响应 201**:
```json
{
  "id": 1,
  "stock_code": "000001",
  "stock_name": "平安银行",
  ...
}
```

**错误码**:
| code | HTTP | 触发条件 | 用户文案 |
|---|---|---|---|
| INVALID_STOCK_CODE | 422 | 股票代码格式错误 | "代码格式错误,核对一下" |
| INSUFFICIENT_SHARES | 422 | 卖出股数超过持仓 | "这只票只剩 X 股了,卖不出 Y 股" |
| INVALID_PRICE | 422 | 价格 ≤ 0 | "价格似乎有问题,核对一下" |
| STOCK_NOT_FOUND | 404 | 股票代码不存在 | "找不到这只股票,核对一下代码" |

**后端副作用**:
1. 同步:写入 `transactions` 表(~5ms)
2. 异步:`BackgroundTasks.add_task(diagnose_service.score_and_notify, trade_id)`
3. SSE 推送 `trade.scored` → `trade.commented`/`trade.failed`

### 3.3 PATCH /api/transactions/{id}
**目的**:修改一笔交易(只能改 note / shares / price / trade_time,不能改 stock_code / action)

**请求体**(所有字段可选):
```json
{
  "shares": 500,
  "price": "10.500",
  "trade_time": "14:38",
  "note": "改备注"
}
```

**响应 200**:同 POST

**业务说明**:改 `trade_time` 会触发成本链重放(同日流水的先后顺序可能变化)与快照重写。

### 3.4 DELETE /api/transactions/{id}
**目的**:删除一笔交易

**响应 204**:无内容

**业务说明**:删除后,持仓自动重算(`safe_write` 保护)

---

## 4. 持仓

### 4.1 GET /api/positions

**目的**:获取当前持仓列表(由 transactions 实时聚合,P3.5.1 起含行情字段)

**响应 200**:
```json
{
  "items": [
    {
      "stock_code": "000001.SZ",
      "stock_name": "平安银行",
      "shares": 1000,
      "avg_cost": "10.333",
      "total_cost": "10333.00",
      "realized_pnl": "399.90",
      "current_price": "10.500",
      "prev_close": "10.000",
      "today_pnl": "500.00",
      "floating_pnl": "167.00"
    }
  ]
}
```

**字段说明**:
- `shares` / `avg_cost` / `total_cost` 来自持仓主数据(positions 表,基准 + 成本链重放)
- **成本口径(v0.17)= 券商摊薄口径**:
  - `avg_cost` = **摊薄成本价** = 摊薄总额 ÷ 股数(= 券商持仓页的「成本价」)
  - `total_cost` = **摊薄总额**(净投入 = 累计买入金额 − 累计卖出金额)
  - `realized_pnl` = 累计已实现盈亏(独立于摊薄总额,不重复计入)
  - 详见 §13.10
- `stock_code` 统一为带市场后缀格式(`600519.SH` / `000001.SZ`,P3.5.1 起)
- `current_price` / `prev_close` 来自行情接口(新浪主 + 腾讯备),缓存 5 分钟
- `today_pnl` = `(current_price - prev_close) × shares`(今日盈亏)
- `floating_pnl` = `(current_price - avg_cost) × shares`(浮动盈亏,按摊薄成本 → 与券商同口径)
- **行情全部失败时**:`current_price` / `prev_close` / `today_pnl` / `floating_pnl` 为 `null`(前端降级显示 "--"),HTTP 仍 200
- 所有金额字段是 **字符串**(精度保护)

**错误码**:
| code | HTTP | 触发条件 |
|---|---|---|
| — | 200 | 行情失败不报错,字段置 null(降级) |

---

## 5. 交易成本计算器

### 5.1 POST /api/calculator

**目的**:试算加仓 / 减仓 / 做T 后新成本 + 21 档盈亏表

**请求体**:
| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| stock_code | str | 是 | 6 位数字或带后缀,如 `600519.SH`(P3.5.1 起统一规范化) |
| action | enum | 是 | buy / sell |
| tx_shares | int | 是 | > 0 |
| tx_price | Decimal | 是 | > 0,3 位小数 |

**响应 200**:
```json
{
  "before": {
    "shares": 1000,
    "cost_price": "10.000",
    "total_cost": "10000.00"
  },
  "after": {
    "shares": 1500,
    "cost_price": "10.333",
    "total_cost": "15500.00",
    "delta_cost": "0.333",
    "realized_pnl": "0"
  },
  "pnl_grid": [
    { "pct": -10, "price": "9.300", "market_value": "13950.00", "pnl": "-1550.00" },
    { "pct": 0, "price": "10.333", "market_value": "15499.50", "pnl": "-0.50" },
    { "pct": 10, "price": "11.366", "market_value": "17049.00", "pnl": "1549.00" }
  ]
}
```

**业务说明**:
- 21 档:`-10%` 到 `+10%`,每 1% 一档,基准 = `after.cost_price`(新成本)
- 加仓算法:加权平均(详见 `core/cost_engine.py`)
- 减仓算法:剩余成本不变,已实现盈亏 = `(tx_price - cost_before) × tx_shares`

**错误码**:
| code | HTTP | 触发条件 |
|---|---|---|
| INSUFFICIENT_SHARES | 422 | 卖出股数超过当前持仓 |
| INVALID_PRICE | 422 | 价格 ≤ 0 |

---

## 6. 单笔交易诊断

### 6.1 POST /api/diagnose/{trade_id}

**目的**:手动触发诊断(通常由 `POST /transactions` 自动触发)

**响应 202**:
```json
{ "trade_id": 1, "status": "pending" }
```

**业务说明**:立即返回,评分通过 SSE 推送

### 6.2 GET /api/diagnose/{trade_id}

**目的**:轮询获取评分(用于 SSE 降级)

**响应 200**:
```json
{
  "trade_id": 1,
  "score": 72,
  "score_breakdown": {
    "集中度": 15,
    "价格合理性": 12,
    "操作间隔": 20,
    "市场环境": 5,
    "板块热度": 0,
    "交易时机": 13
  },
  "ai_comment": "买入价高于成本 8%,疑似追涨...",
  "ai_status": "success",
  "ai_provider": "deepseek",
  "ai_model": "deepseek-chat",
  "ai_latency_ms": 8200
}
```

**业务说明**:`ai_status` 取值:`pending` / `success` / `failed` / `no_key`(v2.1)/ `scored`(只算分未生成评语)

**评分口径**:6 维度 × 20 分 = **满分 120**
(集中度 / 价格合理性 / 操作间隔 / 市场环境 / 板块热度 / **交易时机**)
⚠️ 板块热度当前恒为 0(历史板块排行不可回溯)→ 实际满分上限 100/120

### 6.3 POST /api/diagnose/{trade_id}/regenerate

**目的**:用指定 Provider 重新生成评语(A/B 对比)

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| provider | str | 是 | deepseek / minimax / doubao |

**响应 202**:`{ "trade_id": 1, "status": "pending" }`

### 6.4 POST /api/diagnose/backfill

**目的**:补评 / 全量重算(持仓侧「每一条流水都有评分」)

**请求体**:
| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| stock_code | str | 否 | 全部 | 限定某只股票 |
| force | bool | 否 | false | false = 只补**没有评分**的流水;true = 全部重算 |
| include_comment | bool | 否 | true | false = 只算分不调 LLM(省 token) |
| limit | int | 否 | 200 | 单批上限(1~1000) |

**响应 200**:
```json
{
  "candidates": 6,
  "submitted": 6,
  "trade_ids": [2, 12, 13, 14, 15, 16],
  "force": false,
  "include_comment": true
}
```

**业务说明**:评分在后台跑(SSE `trade.scored` / `trade.commented`),接口立即返回。
幂等:重复执行安全(`trade_scores` 是 upsert)。
**口径升级后必须 `force=true` 全量重算** —— 否则旧的 100 分制分数与新的 120 分制分数混存,不可比。

---

## 7. 止损

### 7.1 GET /api/stop-losses

**响应 200**:
```json
{
  "items": [
    {
      "stock_code": "000001",
      "stop_loss_price": "9.500",
      "enabled": true,
      "notify_sound": true,
      "notify_desktop": true,
      "notify_vibrate": true,
      "last_triggered_at": null
    }
  ]
}
```

### 7.2 POST /api/stop-losses

**请求体**:
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| stock_code | str | 是 | 6 位 |
| stop_loss_price | Decimal | 是 | > 0,3 位小数 |
| enabled | bool | 否 | 默认 true |
| notify_sound | bool | 否 | 默认 true |
| notify_desktop | bool | 否 | 默认 true |
| notify_vibrate | bool | 否 | 默认 true |

**响应 201**:同 GET 单条

### 7.3 DELETE /api/stop-losses/{code}
**响应 204**:无内容

### 7.4 POST /api/stop-losses/{code}/triggered
**目的**:标记止损已触发(幂等,同日重复调用 OK)

**请求体**:空

**响应 200**:`{ "ok": true }`

---

## 8. 年度账单

### GET /api/annual-report/{year}

**路径参数**:`year`(2024~2030)

**响应 200**:
```json
{
  "year": 2026,
  "realized_profit": "12500.00",
  "realized_loss": "8200.00",
  "net_pnl": "4300.00",
  "win_rate": 0.62,
  "top5_profit": [...],
  "top5_loss": [...]
}
```

**业务说明**:`win_rate` 是已平仓持仓的盈利笔数 / 总笔数

---

## 9. 自选股

### 9.1 GET /api/watchlist
**响应 200**:`{ "items": [{ "stock_code": "000001", "stock_name": "平安银行", "source": "manual", "added_at": "..." }] }`

### 9.2 POST /api/watchlist
**请求体**:`{ "stock_code": "000001", "stock_name": "平安银行" }`
**响应 201**

### 9.3 DELETE /api/watchlist/{code}
**响应 204**

---

## 10. SSE 推送

### GET /api/events/sse

**响应**:`text/event-stream`

**事件类型**:
```
event: trade.scored
data: {"event":"trade.scored","trade_id":1,"score":72,"breakdown":{...}}

event: trade.commented
data: {"event":"trade.commented","trade_id":1,"comment":"...","provider":"deepseek","model":"deepseek-chat","latency_ms":8200}

event: trade.failed
data: {"event":"trade.failed","trade_id":1,"reason":"DeepSeek 未配置 Key,请到设置页填写"}

event: ping
data: {"event":"ping","ts":1690890000}   ← 前端过滤
```

**业务说明**:
- 单连接全局,前端按 `trade_id` 过滤
- 心跳 30s/次,死连接 60s 自动清理
- 失败 3 次降级为 5s 轮询 `GET /diagnose/{trade_id}`

---

## 11. LLM Provider 管理

### 11.1 GET /api/llm/providers
**响应 200**:
```json
{
  "items": [
    {"name":"deepseek","model":"deepseek-chat","configured":true},
    {"name":"minimax","model":"abab6.5s-chat","configured":false},
    {"name":"doubao","model":"doubao-pro-32k","configured":false}
  ],
  "active": "deepseek"
}
```

### 11.2 GET /api/llm/settings
**响应 200**:`{ "active_provider": "deepseek" }`

### 11.3 POST /api/llm/settings
**请求体**:`{ "active_provider": "minimax" }`
**响应 200**:`{ "active_provider": "minimax" }`

**错误码**:`INVALID_PROVIDER 422`

### 11.4 GET /api/llm/keys(v2.1 新增)
**目的**:获取 3 Provider 的 Key 配置状态(不返回明文)

**响应 200**:
```json
{
  "deepseek": true,
  "minimax": false,
  "doubao": false
}
```

### 11.5 PUT /api/llm/keys(v2.1 新增)
**请求体**(空字符串 = 不修改 / 清空):
```json
{
  "deepseek": "sk-新key-xxx",
  "minimax": "",
  "doubao": ""
}
```

**响应 200**:`{ "ok": true }`

**业务说明**:
- Key 通过 Fernet 加密后存 `llm_api_keys.encrypted_key`
- `FERNET_KEY` 存 `.env`,首次启动自动生成
- PUT 后立即生效,无需重启
- 不返回明文 Key,前端从不接收

### 11.6 POST /api/llm/test(v2.1 新增)
**请求体**:`{ "provider": "deepseek" }`

**响应 200**:`{ "ok": true, "latency_ms": 1200 }`

**错误码**:
| code | HTTP | 触发 | 用户文案 |
|---|---|---|---|
| NO_KEY | 400 | 未配置 Key | "请先在设置页配置 Key" |
| INVALID_KEY | 401 | 401 错误 | "Key 无效,请核对" |
| FORBIDDEN | 403 | 403 错误 | "Key 权限不足" |
| LLM_TIMEOUT | 504 | 超时 | "连接超时,网络可能不稳" |

---

## 12. 截图识别

### 12.1 POST /api/screenshot/upload

**请求**:`multipart/form-data`,字段 `file`(jpg/png/webp,≤ 5MB)

**响应 202**:
```json
{ "record_id": 1, "status": "pending" }
```

**业务说明**:异步识别,完成后 SSE 推送 `screenshot.parsed` 事件

**错误码**:
| code | HTTP | 触发 |
|---|---|---|
| UNSUPPORTED_FORMAT | 415 | 非 jpg/png/webp |
| FILE_TOO_LARGE | 413 | > 5MB |
| OCR_FAILED | 500 | PaddleOCR 异常 |

### 12.2 GET /api/screenshot/pending
**响应 200**:`{ "items": [{ "id": 1, "screenshot_type": "position", "parsed_items": [...], "created_at": "..." }] }`

### 12.3 POST /api/screenshot/{id}/confirm
**请求体**:
```json
{
  "screenshot_type": "position",
  "items": [
    { "stock_code": "000001", "stock_name": "平安银行", "shares": 1000, "price": "10.500", "confidence": 0.95 }
  ]
}
```

**响应 200**:`{ "ok": true, "inserted": 2 }`

### 12.4 POST /api/screenshot/{id}/reject
**响应 200**:`{ "ok": true }`
**业务说明**:删除原图 `~/rich/uploads/{uuid}.jpg`

### 12.5 POST /api/screenshot/parse-paste(降级路径)
**请求体**:
```json
{
  "screenshot_type": "position",
  "items": [...],
  "confidence": 0.9
}
```

**响应 200**:`{ "record_id": 2, "items": [...] }`

---

## 13. 场内 ETF 品种与规则(v0.6 新增)

> 场内 ETF / 场内 LOF 与股票的**交易规则不同**:免印花税、免过户费、无涨跌停限制、
> 跨境/商品类当日可回转(T+0)。本节记录与品种相关的契约差异。
> 完整设计与实测记录见 `docs/etf-rfc.md`(实施规格 v1.0)。

### 13.1 GET /api/stock/{code}/industry

**目的**:标的行业归属(ETF 返回其跟踪指数)

**响应 200**:
```json
{
  "code": "513120.SH",
  "industry": "跟踪中证香港创新药",
  "source": "etf_index",
  "note": "场内 ETF · QDII"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | string | 规范化代码(带市场后缀) |
| `industry` | string \| null | 股票=行业名;ETF=「跟踪 {指数}」;查不到=null(**不编造**) |
| `source` | string | `baostock`(离线行业表)/ `etf_index`(ETF 品种表)/ `sina`(行情排行榜反查) |
| `note` | string \| null | ETF 附注(形态 · 类别),如「场内 ETF · QDII」;股票为 null |

**错误**:代码格式非法 → 422 `INVALID_STOCK_CODE`

### 13.2 GET /api/stock/{code}/analysis —— 新增三个字段

在既有响应体上新增(节点缓存命中与未命中**两条路径都注入**):

| 字段 | 类型 | 说明 |
|---|---|---|
| `industry` | string \| null | 同 13.1 |
| `industry_source` | string \| null | 同 13.1 的 `source` |
| `industry_note` | string \| null | 同 13.1 的 `note` |

其余字段(含 `indicators` / `ai` / `degraded`)结构不变。

### 13.3 POST /api/calculator 与 POST /api/calculator/review —— 按品种选费用档

**请求体与响应结构不变**,行为按标的品种分流:

| 项 | 股票 | 场内 ETF / LOF |
|---|---|---|
| 费用档 | 印花税 + 过户费 + 佣金 | **免印花税、免过户费**,佣金沿用用户配置 |
| `t_directions.*.t_plus_one_note` | 「A 股 T+1:当天买入的股票当天不能卖出…」 | T+0 品种→「该品种为 T+0(当日可回转):当天买入的份额当天就能卖出…(具体以交易软件显示的品种属性为准)」 |
| `t_directions.forward.max_shares`(正T 上限) | `min(可动T仓 M, 资金可买股数)` | **T+0 品种:只受资金约束** `floor(可用资金 ÷ 买价)` |
| `t_directions.reverse.max_shares`(反T 上限) | 受可动 T 仓约束 | 同左(不变) |

**降级**:代码符合 ETF 格式但**未在品种表内**的标的,按保守口径(T+1 / 股票费率)计算,
并在 `degraded` 中明说「该 ETF 未在品种表内,已按保守口径(T+1 / 股票费率)计算,交易规则可能有偏差」。
**不静默、不假装已知**,也不因此报错。

### 13.4 GET /api/annual-report/{year}

逐笔按标的品种选费用档(ETF 免印花税/过户费);响应结构不变。

### 13.5 错误码

本次**无新增错误码**。表外 ETF 不报错 —— 按保守口径降级 + 明说降级原因。

---

## 13.6 操作决策与操作建议(v0.10 新增)

### 13.6.1 GET /api/stock/{code}/decision

**目的**:确定性决策卡(零 LLM、纯算法、秒出)+ 卡内「操作建议」区。

**响应 200**:
```jsonc
{
  "decision": {
    // —— 既有字段(语义不变)——
    "stock_code": "002185.SZ",
    "verdict": "hold",
    "headline": "现价 16.19 元,等触发:涨到 19.16 元可解套(需涨 5.1%)",
    "role": "解套参考",
    "confidence": "medium",
    "position_status": "loss",
    "actions": [ /* Action[] */ ],
    "stop_loss": { "price": 13.2, "basis": "跌破即止损" },
    "position_pct": "解套优先,减仓不追补",
    "do_not": ["下跌通道中不要抄底"],
    "t_plan": { /* TPlan */ },
    "trend_state": { "phase": "下跌通道·延续", "note": "..." },
    "market_env": { /* MarketContext */ },

    // —— v0.10 新增(纯增量)——
    "grid_plan": {
      "suitable": false,
      "mode": null,
      "reason": "",
      "range_low": null, "range_high": null, "span_pct": null,
      "grids": null, "step_pct": null, "step_price": null,
      "shares_per_grid": null, "capital_per_grid": null,
      "cash_needed": null, "cash_available": null,
      "net_step_pct": null, "roundtrip_fee_pct": null, "fee_basis": null,
      "net_profit_per_grid": null,
      "replace_t_plan": false,
      "risk": "",
      "unsuitable_signals": "下跌通道中不要布网格:越买越套"
    },
    "suggestions": {
      "price":     { "label": "价位", "value": "涨到 19.16 元可解套(需涨 5.1%)" },
      "stop_loss": { "label": "止损", "value": "13.20 元(距现价 -18.5%)" },
      "position":  { "label": "仓位", "value": "解套优先,减仓不追补" },
      "trigger":   { "label": "触发", "value": "涨到 19.16 元(P80 分位)" },
      "timing":    { "label": "时间", "value": "已持有 23 天,回本还需 +5.1%" },
      "avoid":     { "label": "不动", "value": "下跌通道中不要抄底" }
    },
    "advice": {
      "headline": "现价 16.19 元,等触发:涨到 19.16 元可解套(需涨 5.1%)",
      "bullets": ["价位:...", "网格不建议:...", "止损 ... · 仓位 ..."],
      "source": "rule"
    },
    "cost_anchor":    { "cost_basis": 17.02, "current_price": 16.19, "pnl_pct": -4.88,
                        "break_even_gap_pct": 5.12, "distance_to_stop_pct": -18.47,
                        "distance_to_target_pct": null, "risk_reward": null },
    "time_window":    { "holding_days": 23, "source": "transactions", "overdue": true,
                        "overdue_text": "已超 20 天阈值 3 天",
                        "note": "已持有 23 天(自然日,起点=最早一笔流水)" },
    "cost_effect":    { "roundtrip_fee_pct": 0.102, "fee_basis": "default_estimate",
                        "spread_pct": 9.7, "worth_it": true, "note": "..." },
    "instrument_rule":{ "kind": "stock", "t0": false, "notes": ["股票有涨跌幅限制(±10%)", "T+1,..."] },
    "concentration":  { "cost_share_pct": 12.0, "level": "low", "note": "..." },

    "data_quality": { "degraded": ["费用设置未启用,费用按默认档估算"] }
  }
}
```

**约定**:
- `suggestions` 六格**值可为 `null`**(= 该维度数据不足,前端整格不渲染,不显示空框);
- `grid_plan` **始终存在**;不适适时配置类字段一律 `null`,原因写在 `unsuitable_signals`;
- `advice.source` 恒为 `"rule"` —— 决策端点**零 LLM**,白话是规则拼的,不是模型写的;
- 五个维度**只增信息**,不改变 `verdict` / `actions` / `t_plan` 的既有判定。

### 13.6.2 GET /api/stock/{code}/decision-advice

**目的**:把决策事实包翻译成大白话(**按钮触发**,不在首屏自动烧 token)。

**响应 200**:
```json
{
  "advice": {
    "headline": "离回本还差 5.1%,别急着补仓",
    "bullets": ["跌破 13.20 元止损", "涨到 19.16 元再减"],
    "source": "llm",
    "generated_at": "2026-10-25T18:20:31"
  },
  "degraded": []
}
```

**降级**:
- LLM 未配置 / 超时 / 解析失败 → `source="rule"`(退回规则文案),**仍 200**,卡片永不空白;
- K 线完全不可用 → 502 `DATA_SOURCE_UNAVAILABLE`(与 `/decision` 一致);
- 进程内**当日缓存**(key = 代码 + 日期 + headline 摘要),跨日自动失效。

### 13.6.3 GET /api/stock/{code}/analysis(v0.10 变更)

- 响应结构**不变**;AI 不可用时 `ai=null` 行为不变;
- **变更**:提示词追加「决策事实包」(JSON),并加硬规则「数字必须原样引用,冲突时以事实包为准」;
- **不增加网络 IO**:事实包复用本端点已有的 klines / quote / position;
  市场环境**不纳入**事实包(那是 4~5 次外部 HTTP),「大盘普跌时不要加仓」由决策卡承担。

---

## 13.7 K 线异动行为标注与找股模块(v0.15 新增)

> 四类异动行为标注:主力异动 / 低吸信号 / 锁仓信号 / 高抛信号。
> **定位**:日线级别的**形态回溯标注** —— 回答「历史上某一天出现了什么可观测事实」。
> 与 `modules/signal`(盘中实时推送,ADR-0007)是**两回事**。
>
> ⚠️ **措辞纪律**:标注只陈述已发生的事实,**不预测涨跌、不给买卖指令**。
> 「低吸」「高抛」是形态名称,不是操作建议。

### 13.7.1 GET /api/kline/{code}/indicators(v0.15 追加字段)

响应**追加**两个字段,既有字段(`items` / `indicators` / `signal_series` 等)**完全不变**:

```jsonc
{
  "stock_code": "600519.SH",
  "period": "daily",
  "count": 300,
  "items": [ /* 不变 */ ],
  "indicators": { /* 不变 */ },

  // 新增:异动行为标注点(按日期升序)
  "behavior_markers": [
    {
      "kind": "dip_buy",              // main_force_move | dip_buy | lock_position | distribute
      "date": "2026-10-28",
      "date_index": 288,
      "text": "🔻 低吸信号",
      "position": "belowBar",         // aboveBar | belowBar
      "color": "#22d3ee",
      "reason": "主力净额由 -0.79 亿转 +0.39 亿；下影 2.31 ≥ 实体 1.10×1.5；收盘 1330.75 回踩 MA20 1341.20（偏离 0.8%）；量比 0.94",
      "metrics": { "main_net_yi": 0.39, "volume_ratio": 0.94, "ma20": 1341.2 }
    }
  ],
  // 新增:资金流不可用时为 true(此时 behavior_markers 为空数组)
  "behavior_markers_unavailable": false
}
```

**降级语义**:
- 资金流历史不可用 → `behavior_markers=[]` + `behavior_markers_unavailable=true`,
  **K 线与既有指标照常返回 200**(资金流是「锦上添花」,失败就如实说不可用);
- K 线不足 120 根 → 不产出标注(`behavior_markers=[]`),`behavior_markers_unavailable=false`
  (数据够,只是不够算);
- **非日线周期**(weekly/monthly/minute)→ 不产出标注(口径不同,不误导);
- 只回传最近 60 个日历日内的标注(控制响应体)。

**前端注意**:前端需把 `behavior_markers` 与既有 `signal_series` **合并后按 time 排序**
再调 `setMarkers` —— lightweight-charts 要求数组按 time 有序,否则抛错且标注整体消失。

### 13.7.2 找股模块 `/api/behavior-screener`

> ⚠️ 与 `/api/screener`(选股)口径不同:
> - 选股:按**因子打分**(主力净流入/量比/动能/板块强度/事件热度)排 Top 20
> - 找股:按 **K 线行为信号命中**分组

#### GET /api/behavior-screener/latest

**查询参数**:

| 参数 | 默认 | 范围 | 说明 |
|---|---|---|---|
| `kind` | 不传 | 信号 kind | 只看某一类;**传了才返回 `page`** |
| `limit` | 60 | 1 ~ 200 | `page.picks` 每页条数 |
| `offset` | 0 | ≥ 0 | `page.picks` 偏移 |

**响应 200**:
```jsonc
{
  "run": {
    "id": 1,
    "run_date": "2026-10-30",
    "generated_at": "2026-10-30T15:40:12",
    "pool_size": 5574,          // 全市场快照总数
    "main_board_count": 3193,    // 主板闸门后
    "non_st_count": 3053,        // 非 ST 后
    "after_filters_count": 1941, // 成交额 ≥ 1 亿后
    "candidates_considered": 1941, // 进入逐票算信号的候选数(**不再截断**)
    "total_picks": 402,          // 本批**真实命中总数**
    "hit_counts": {              // 各 kind 的**真实命中数**(与 total_picks 对得上)
      "main_force_move": 268,
      "dip_buy": 95,
      "lock_position": 31,
      "distribute": 8
    },
    "data_as_of": "2026-10-30",  // 本批数据中**已收盘**的最后交易日
    "is_intraday": false,        // 本批是否含当日未收盘数据;null = 时点未知
    "elapsed_sec": 8.2,
    "note": null
  },
  "groups": [
    {
      "kind": "dip_buy",
      "kind_label": "低吸信号",
      "count": 95,               // 该类**真实命中数**(≠ picks.length)
      "picks": [ /* 只带前 60 条明细 */ {
          "stock_code": "600519.SH",
          "stock_name": "贵州茅台",
          "kind": "dip_buy",
          "kind_label": "低吸信号",
          "signal_date": "2026-10-28",
          "days_ago": 2,
          "reason": "主力净额由 -0.79 亿转 +0.39 亿；…",
          "metrics": { "main_net_yi": 0.39 },
          "score": 88.0,
          "change_pct": 0.89
      } ]
    }
  ],
  "all": [ /* 只带前 60 条,按综合分降序 */ ],
  "kinds": [ { "kind": "main_force_move", "label": "主力异动" } ],
  "page": {                      // ⚠️ 仅当传了 kind 才出现
    "kind": "dip_buy",
    "offset": 0,
    "limit": 60,
    "total": 95,                 // 该类真实总数(≠ 本页条数)
    "picks": [ /* 该类第 offset..offset+limit 条 */ ]
  }
}
```

**口径要点(2026-10-31 起)**:

- `count` / `page.total` 是**真实命中数**,`groups[].picks` / `page.picks` 是**分页后的明细** ——
  两者**故意不等**(如 95 vs 60)。前端要显示真实数就取 `count`,要取明细就走 `page` 分页。
- `groups[].picks` 与 `all` 每类只带前 **60** 条(`BEHAVIOR_SCREENER_GROUP_PAGE_N`),
  超过部分靠 `?kind=&limit=&offset=` 拉 —— **不存在**「一次拿到全部明细」的入口。
- `candidates_considered` 现在**等于** `after_filters_count`(候选池不再截断)。
- `hit_counts` 是**可能为 null 的字典**:存量批次行没有 `hit_counts_json` 时 → `{}`,
  此时 `count` 兜底为**已加载行数**(不填 0)。

> 🚨 **前端必读:字典的「键」也会被驼峰化**。axios 响应拦截器递归转换**每一个对象的键**,
> 所以 `hit_counts` 里的 `"main_force_move"` 到前端会变成 **`mainForceMove`**。
> → **按类取真实数一律走 `groups[].count`**(`groups[].kind` 是**值**,不会被驼峰化),
> **不要用 `hitCounts[kind]`** —— 那是运行期 `undefined`,而 TS 的 `Record<string, number>`
> **不报错** → 会静默退回 `picks.length`,让真实计数彻底失效。

**降级**:
- 尚无批次 → **404**(前端据此显示「还没跑过」,与「跑了但没命中」区分开);
- 全市场快照不可用 → 跑批失败,返回 502。

#### GET /api/behavior-screener/runs?days=N

返回最近 N 天批次列表(默认 10,上限 90)。

#### GET /api/behavior-screener/pool

返回候选池口径统计(未跑过时 `universe=null` + `note="尚无批次,未统计"`,**不编数字**)。

#### POST /api/behavior-screener/trigger-now

手动重跑(默认今日)。
- **生产禁用**:需环境变量 `SCREENER_ALLOW_TRIGGER=1`,否则 **403**(与 `/screener/trigger-now` 同口径);
- 候选池**不再截断**(`BEHAVIOR_SCREENER_CANDIDATE_LIMIT=None`)→ 单批候选约 1900+ 只,
  每只 2 次外网请求(K 线 + 资金流),墙钟耗时取决于外网行情源 → 前端超时设 **300s**;
- 响应体的 `all` 是**全部命中**(无上限),单批可达数百条 → 响应体量级为数百 KB。

### 13.7.3 判定阈值与打分口径(v0.15 定稿)

> 阈值全部外置 `backend/app/core/config.py`(`BEHAVIOR_*` 前缀),便于回测调参。
> 下表是 **2026-10-30 全市场真机校准后的定稿值** —— 初版偏松(大盘普涨日命中率达 81%),
> 已收紧。**换市场环境仍可能失配**,需持续回测调整。

| 信号 kind | 判定条件 |
|---|---|
| `main_force_move` | `r0_net` > 0 且 `r0x_ratio` ≥ **65%** 且 涨幅 ≥ **2%** 且 量比 ≥ **1.5** |
| `dip_buy` | 主力净额由负转正(≥ 0 亿) + 下影 ≥ 实体×1.5 + 收盘回踩 MA20(偏离 ≤ 3%) + 量比 ≤ 1.0 |
| `lock_position` | 连续 5 日主力净额为正且累计 ≥ 0.5 亿 + 期间振幅 ≤ 8% + 期间均量 ≤ 前 5 日均量×0.9 |
| `distribute` | 主力净额由正转负(≤ 0 亿) + 上影 ≥ 实体×1.5 + 距近 20 日高 ≤ 5% + 量比 ≥ **1.5** |

**强度分级(仅 `main_force_move`,其余三类按各自形态指标归一)**

四个维度的「过线进度」`进度 = (实测值 − 判定线) / (强线 − 判定线)`,截断到 `[0,1]`:

| 维度 | 判定线 | 强线 |
|---|---|---|
| 主力净占比 `r0x_ratio` | 65% | 85% |
| 涨跌幅 `change_pct` | 2% | 7% |
| 量比 `volume_ratio` | 1.5 | 3.0 |
| 超大单净额 `r0_net_yi` | 0 | 5 亿 |

- 强度进度 = 四维**均值**;强度系数 = `0.5 + 1.5 × 进度`(范围 0.5 ~ 2.0);
- 等级「强 / 一般」由**同一个进度**决定(≥ **0.6** 为强)—— 等级与分数同源,不自相矛盾;
- `metrics` 里 `strength_level` 是**字符串枚举**(`"强"` / `"一般"`)、`strength_note` 是说明文字、
  `strength_progress` 是 0~1 的数值 —— 前端 `metrics` 类型须允许字符串。

**打分口径**

```
score = 类型权重 × 新鲜度系数 × 强度系数 × 100
```

- 类型权重:主力异动 1.0 / 低吸 1.2 / 锁仓 1.1 / 高抛 0.9(`BEHAVIOR_SCREENER_KIND_WEIGHTS`);
- 新鲜度系数:`0.85 ^ days_ago`,下限 0.3;
- **×100 是必需的**:不放大时分数落在 1.3 ~ 1.5,排序差异肉眼不可辨、等于随机。
  放大后实测落在 **18.9 ~ 147.0**(极差 128.1),Top 12 无并列。

**`change_pct` 的口径(易错)**

`change_pct` 是**信号当日**的涨跌幅,**不是**跑批当天的涨跌幅 —— 它显示在
「信号日 2026-10-30(1 天前)」旁边,必须与 `reason` 里说的「当日涨跌」是同一天。

- 取值优先:`metrics.change_pct`(主力异动判定用的实测值,与 `reason` 逐字一致);
- 其余三类信号从 K 线算(`close[i] / close[i-1] - 1`);
- 算不出 → `null`(前端显示 `-`),**不编数字**。

⚠️ **前端类型必须写驼峰**:axios 响应拦截器会递归把 snake_case 转成 camelCase,
前端 API 层的 TS 类型写成 snake_case 时 TS 不报错,但运行期读出来全是 `undefined`
(口径条会渲染成「主板 只 · 非 ST 只」这种**空数字**)。

---

## 13.8 做T挂单清单(待接回 + 待卖出)(v0.16 新增 · v0.18 改为双向 · v0.19 三档 + 自动提醒)

### 13.8.1 GET /api/t-reminders/pending

**目的**:把「还挂着的做T单」列出来 —— 这是左栏第一位「🔁 补T提醒」清单的数据源。

**做T有两个方向**(v0.18 起明确区分):

| 组 | `direction` | 中文 | 腿的顺序 | 挂单含义 |
|---|---|---|---|---|
| 待接回 | `reverse` | 反T | 先卖出 → 后买回 | 高抛低吸,卖出了还没买回来 |
| 待卖出 | `forward` | 正T | 先买入 → 后卖出 | 低吸高抛,买进了还没卖出去 |

**口径(单一,不搞多套推断)**

1. 每只标的的**全部流水**按链全序(`trade_date, trade_time or min, id`)走一遍,**双向 FIFO**:
   - 遇到**买入**:先闭合最早的**卖出开腿**(反T),剩余部分成为**买入开腿**(正T);
   - 遇到**卖出**:先闭合最早的**买入开腿**(正T),剩余部分成为**卖出开腿**(反T);
2. **配对有时间窗口**:开腿与收腿相隔超过 `T_PAIR_WINDOW_DAYS`(默认 **3** 天)就不算一次做T ——
   超窗口的开腿被**冻结**,不再参与后面的配对,单独作为加仓/减仓挂着;
3. 链尾**还没被闭合的开腿** = 还挂着的做T单;**开腿日期也要落在窗口内**
   (基准 = 链上最后一个流水的日期,确定性,不随「今天」漂移);
4. 同一标的 + 同一方向的多笔挂单**合并成一条**(股数累加、金额累加 → 加权均价);
5. **基准线**:
   - 反T = **不亏本接回线** = 净卖出加权均价 —— 接回价高于它,这次 T 就是做亏的;
   - 正T = **买入加权均价**;
6. **三档建议价(v0.19 新增)** —— 每档给「价格」+「按这档成交之后的成本前→后」:

   | 档 | 幅度 | 反T(待接回) | 正T(待卖出) | 含义 |
   |---|---|---|---|---|
   | 一档 | 1% | 基准线 × 0.99 | 基准线 × 1.01 | 贴线,最容易成交 —— 先把这单做掉 |
   | 二档 | 2% | 基准线 × 0.98 | 基准线 × 1.02 | 幅度与成交概率折中 |
   | 三档 | 3% | 基准线 × 0.97 | 基准线 × 1.03 | 幅度最大,可能要等行情 |

   **两组的档位方向相反**:反T 三档往下走(越等接回越便宜),正T 三档往上走(越等卖得越贵)。
   不能一味价高 —— 一味价高在反T 上就是「接回价比卖出价还高,做出来是亏的」。

   > 幅度常量集中在 `app/modules/portfolio/t_pricing.py` 的 `TIER_OFFSETS`,
   > 改幅度不改结构。0.5% 太小(只够覆盖双边手续费),所以改成 1% / 2% / 3%。

7. **每档的成本前→后**(摊薄口径,见 §13.10):
   - 反T(接回)= (当前摊薄总额 + 该档价格 × 待接回股数) / (当前持仓 + 待接回);
   - 正T(卖出)= (当前摊薄总额 − 该档价格 × 待卖出股数) / (当前持仓 − 待卖出);
   当前成本线取持仓行的**摊薄成本**(= 券商持仓页口径,见 §13.10)。

**为什么要有时间窗口**:做T是**短周期**动作(当天卖、次日接回,周五卖下周一接回也正好 3 天)。
没有窗口的话,「10 月 13 日买的票,11 月 2 日割掉」会被当成一次正T,
而「今天卖、明天接回」也会因为更早的一笔买入而被**配错腿** ——
2026-11-03 的中钨高新就是例子:10-13 买、11-02 卖、11-02 买、11-03 买,
没有窗口时 11-02 的卖会先去配 10-13 的买,导致「当天做的那笔T」散架、
真正的今日加仓反而被算成接回腿。

**为什么从「只看最近一个交易日」改成全链(v0.18)**:卖出腿和接回腿天然可能跨天。
v0.16 的口径会把「卖 200 只接回 100」剩下的 100 股直接丢掉 —— 用户根本看不到还差多少。
改成全链后,**没配上的那条腿**才是挂单,跨几天都留着,直到接回/卖出为止。

> 副作用:卖出后长期不接回(可能是「减仓」不是「做T」)在窗口内也会挂着。
> `open_date` 字段给出挂单起始日,便于判断这是不是陈年旧账。

**建议价必须落在最小报价单位上**:按 3 位小数 `ROUND_HALF_UP` 量化,挂单才合法。

### 13.8.2 到价提醒自动管理(v0.19 新增)

**每条挂单都保证有一条到价提醒**,方向跟T方向一致:

| 方向 | 提醒条件 | 触发时机 |
|---|---|---|
| 反T(待接回) | `price <= 一档价` | 跌下来 → 提醒接回 |
| 正T(待卖出) | `price >= 一档价` | 涨上去 → 提醒卖出 |

**落在哪一档**:自动提醒**新建**时建在**一档** —— 一档是行动信号(该动手了),
二/三档是「愿意多等一会儿换更好价」的选择。
**用户把自动提醒改到二档/三档,系统认**(不会被拉回一档)—— 三档摆在那里就是为了让人选,
系统不该替用户改主意。只有当提醒的价格**不落在当前任何一档**上时(基准线变了,
或被改成了档位外的自定义价),才把这条提醒**就地**改回一档(不新建、不停用)。

一句话:**有提醒就复用,提醒的档位由用户定;提醒跟不上了才拉回一档。**

**怎么标记「这条是系统自动建的」**:`PriceAlert` 没有 source / metadata 字段,
只能用 `name` 前缀 **`[做T]`** 标记(如 `[做T]豫能控股 反T接回`)。
**只对带前缀的提醒做自动停用** —— 用户手工建的提醒一律不碰。

**同步时机**:在 `GET /api/t-reminders/pending` 里做(**幂等**)。打开页面即对齐,
不用用户点「建提醒」。同步做三件事:

1. 每条挂单:若已存在该标的该方向的**启用自动提醒** → 直接复用
   (价格落在当前任一档就保留,否则就地改回一档);
   否则看用户手工建的那条是否正好命中一档价 → 命中就复用(不重复建);
   都没有 → **新建**一条 `[做T]` 自动提醒(一档价);
2. 用户手工建的提醒(同标的 + 同方向,价格命中基准线或任一档位)单独记在
   `manual_alert_id` / `manual_alert_price` —— **不会被自动停用**;
3. 带 `[做T]` 前缀、但**已经对不上任何挂单**的提醒 → **停用**(`enabled = false`,
   不是删除,保留触发历史)。挂单接回/卖出 → 从清单消失 → 提醒自动停用。

**基准线变了怎么办**:又卖了一笔 → 加权均价变 → 一档价变 → 原来那条自动提醒**就地**
改成新的一档价(同一条 id,不新建、不停用)。提醒始终跟着当前建议价走。

**响应 200**:
```jsonc
{
  "items": [                       // 待接回(反T)
    {
      "stock_code": "001896.SZ",
      "stock_name": "豫能控股",
      "direction": "reverse",
      "shares": 100,              // 待接回股数
      "price": 8.86,              // 不亏本接回线(加权均价)= 基准线
      "suggested_price": 8.771,   // 一档建议接回价(基准线 × 0.99)—— 兼容字段
      "tiers": [                  // 三档建议价(每档带成本前→后)
        {
          "tier": 1, "label": "一档",
          "price": 8.771, "offset_pct": 0.01,
          "cost_before": 16.910, "cost_after": 15.554,
          "hint": "贴线,最容易成交 —— 先把这单做掉"
        },
        {
          "tier": 2, "label": "二档",
          "price": 8.683, "offset_pct": 0.02,
          "cost_before": 16.910, "cost_after": 15.539,
          "hint": "幅度与成交概率折中"
        },
        {
          "tier": 3, "label": "三档",
          "price": 8.594, "offset_pct": 0.03,
          "cost_before": 16.910, "cost_after": 15.524,
          "hint": "幅度最大,可能要等行情"
        }
      ],
      "open_date": "2026-11-02",  // 挂单起始日(该组最早未闭合开腿的日期)
      "position_shares": 500,     // 当前持仓股数
      "current_price": 8.83,      // 现价;行情取不到 → null(不编数字)
      "alert_id": 5,              // 到价提醒 id(自动保证存在)
      "alert_price": 8.771,       // 该提醒的触发价
      "alert_tier": 1,            // 该提醒落在第几档
      "alert_auto": true,         // 是不是系统自动建的
      "manual_alert_id": 4,       // 用户手工建的提醒(同标的 + 同方向);没有 → null
      "manual_alert_price": 8.86,
      "pre_alert_id": 9,          // 提前预警提醒 id(自动保证存在);没有 → null
      "pre_alert_price": 8.859,   // 预警线 = 生效到价线朝基准线方向再退 1%
      "pre_alert_fired": false,   // 这条预警是否已经响过
      "pre_alert_distance_pct": 0.67,  // 现价离到价线还差百分之几(绝对值)
      "pre_alert_reached": false, // 现价是否已越过到价线
      "pre_alert_in_zone": true,  // 现价是否已进入预警区(离到价线还差 1% 以内)
      "cost_before": 16.910,      // 当前成本线(摊薄成本价,券商口径)= 一档的 cost_before
      "cost_after": 15.554        // 按一档价接回后的摊薄成本线
    }
  ],
  "count": 1,                     // 待接回条数
  "forward_items": [              // 待卖出(正T)
    {
      "stock_code": "561980.SH",
      "stock_name": "半导体设备ETF招商",
      "direction": "forward",
      "shares": 200,
      "price": 0.442,             // 买入加权均价 = 基准线
      "suggested_price": 0.446,   // 一档建议卖出价(基准线 × 1.01)
      "tiers": [
        { "tier": 1, "label": "一档", "price": 0.446, "offset_pct": 0.01,
          "cost_before": 0.717, "cost_after": 0.825, "hint": "贴线,最容易成交 —— 先把这单做掉" },
        { "tier": 2, "label": "二档", "price": 0.451, "offset_pct": 0.02,
          "cost_before": 0.717, "cost_after": 0.823, "hint": "幅度与成交概率折中" },
        { "tier": 3, "label": "三档", "price": 0.455, "offset_pct": 0.03,
          "cost_before": 0.717, "cost_after": 0.822, "hint": "幅度最大,可能要等行情" }
      ],
      "open_date": "2026-11-03",
      "position_shares": 700,
      "current_price": 0.436,
      "alert_id": 8,
      "alert_price": 0.446,
      "alert_tier": 1,
      "alert_auto": true,
      "manual_alert_id": null,
      "manual_alert_price": null,
      "pre_alert_id": 12,
      "pre_alert_price": 0.442,
      "pre_alert_fired": false,
      "pre_alert_distance_pct": 2.29,
      "pre_alert_reached": false,
      "pre_alert_in_zone": false,
      "cost_before": 0.717,
      "cost_after": 0.825
    }
  ],
  "forward_count": 1,             // 待卖出条数
  "total_count": 2,               // 两组合计
  "as_of": "2026-11-03",          // 基准日(各挂单开腿日的最大值)
  "auto_alerts_created": 0,       // 本次同步自动新建的提醒条数
  "auto_alerts_disabled": 0,      // 本次同步自动停用的提醒条数(挂单已消失)
  "auto_alerts_realigned": 0,     // 本次同步把提醒就地拉回一档的条数
  "pre_alerts_created": 4,        // 本次同步自动新建的**预警**提醒条数
  "pre_alerts_rearmed": 0,        // 价格离开预警区后被重新武装的条数
  "pre_alerts_disabled": 0,       // 挂单消失后被停用的预警条数
  "pre_alerts_realigned": 0       // 预警线就地跟到新价的条数
}
```

> `cost_before` / `cost_after` 在没有持仓行时:`cost_before = null`、`cost_after = null`
> (不编数字);三档的 `cost_before` / `cost_after` 同样留 null,但**三档价格照样给得出**
> (只依赖基准线)。

**前端类型必须写驼峰**(axios 响应拦截器递归 snake_case → camelCase):`stockCode` /
`stockName` / `direction` / `suggestedPrice` / `tiers[]`(`tier` / `label` / `price` /
`offsetPct` / `costBefore` / `costAfter` / `hint`)/ `openDate` / `positionShares` /
`currentPrice` / `alertId` / `alertPrice` / `alertTier` / `alertAuto` / `manualAlertId` /
`manualAlertPrice` / `preAlertId` / `preAlertPrice` / `preAlertFired` /
`preAlertDistancePct` / `preAlertReached` / `preAlertInZone` / `costBefore` / `costAfter`;
列表层 `forwardItems` / `forwardCount` / `totalCount` / `autoAlertsCreated` /
`autoAlertsDisabled` / `autoAlertsRealigned` / `preAlertsCreated` / `preAlertsRearmed` /
`preAlertsDisabled` / `preAlertsRealigned`。

### 13.8.3 提前预警(v0.20 新增)

**问题**:到价提醒是「价格到了才响」—— 但**到了再响,已经没有操作空间了**。
挂单是「到了一档价就动手」,而实际操作需要提前把单子准备好。

**口径**(用户选定):**预警线 = 生效到价线朝基准线方向再退 1%**,数值上 ≈ 基准线。

| 方向 | 生效到价线(一档) | 预警线 | 含义 |
|---|---|---|---|
| 反T(待接回) | 基准线 × 0.99 | 到价线 × 1.01 | 价格**涨回**基准线附近 → 该准备接回了 |
| 正T(待卖出) | 基准线 × 1.01 | 到价线 × 0.99 | 价格**跌回**基准线附近 → 该准备卖出了 |

方向与到价线**相反**(到价线是「等价格过来」,预警线是「提前站在价格来的路上」)。
预警线基于**生效到价线**而不是固定基准线 —— 用户把到价提醒改到二档,预警线就跟着按二档算,
**永远早一步**。

**实现形态**:预警是**独立的一条 `PriceAlert`**,不复用条件树双阈值:

- `name` 前缀 **`[做T·预警]`**(与到价提醒的 `[做T]` 不重叠 —— `[做T·预警]` 不以 `[做T]` 开头);
- 条件树**顶层**带 `kind = "pre_alert"` 与 `once = true`;
- 引擎不认识 `kind` / `once`,只透传(见 `engine.notification_meta`),alert 模块保持通用。

**一次性 + 重新武装**:预警命中后自动停用(不删除,保留触发历史);
但价格**离开**预警区后**由后端调度器**重新武装 —— 「一次性」不等于「一辈子只提醒一次」。

> ⚠️ 重新武装必须由**后端调度器**承担,不能只挂在清单页同步里:
> 页面关着就不会同步 → 预警响一次就哑了 → 与「页面关着也能收到」的诉求直接冲突。
> 判据是**当前价不再满足预警条件**(与「命中」互为补集),不需要知道方向,也不需要知道预警线是多少 ——
> 条件树本身就是判据。行情取不到 → 不做任何动作(宁可少武装一次,也不编数据)。
> 落在 `alert/service.py::rearm_pre_alerts()` + `alert/scheduler.py`(每轮扫描后调用)。

**挂单消失** → 到价提醒与预警提醒都**停用不删除**。

**实时数据**(live API 验证):
```
REVERSE 001896.SZ 触发=8.771 预警=8.859 距离=0.67%  inZone=True   reached=False
FORWARD 000657.SZ 触发=36.34 预警=35.977 距离=1.91%  inZone=False
FORWARD 002185.SZ 触发=14.494 预警=14.349 距离=4.42% inZone=False
FORWARD 561980.SH 触发=0.446 预警=0.442  距离=2.29%  inZone=False
```

**UI 口径**:清单页新增「预警线 · 还差」列 —— 显示 `还差 X%` / `已进入准备区` / `已越过 X%` /
`已预警`;弹窗区分两种徽章:琥珀色 `warn`「准备」(预警)与涨跌色「涨到/跌到」(到价)。
预警用中性/琥珀色,**不占用行情红绿语义色**。

### 13.8.4 提醒实时推送与应用内弹窗(v0.20 新增)

**背景**:到价提醒原本只有「后端推系统通知」这一条路。但实测在 Windows 11 26200 上,
WinRT Toast 因**非打包进程没有 package identity** 被平台拒(`0x80073D54`),
降级到 Win32 托盘气泡后 `ShowBalloonTip` **返回成功但屏幕上什么都没画出来**
(抓屏证实右下角托盘区域无任何气泡)。也就是说 —— 用户在「通知设置」里把桌面通知打开、
点「测试」也显示成功,但**真到价了仍然收不到任何可见提示**。

所以补了一条**不依赖系统通知**的通道:提醒触发 → 事件总线 → SSE → 网页内弹窗。
只要页面开着就一定看得见。

#### GET /api/price-alerts/stream(SSE)

**帧格式**(SSE `data:` 行,JSON):

| 帧 | 何时 | 载荷 |
|---|---|---|
| `price_alert_snapshot` | **建连首帧** | `{ event, items: PriceAlertFiredEvent[] }` —— 最近 10 分钟内**真的响了**的提醒(补断线期间漏掉的) |
| `price_alert_fired` | 提醒命中**且通过冷却/日限流**时 | `PriceAlertFiredEvent` |

`PriceAlertFiredEvent`:
```jsonc
{
  "event": "price_alert_fired",
  "trigger_id": 769,                    // 触发流水 id —— 前端靠它去重
  "triggered_at": "2026-11-04T09:31:00",
  "alert": {
    "id": 4,
    "stock_code": "001896.SZ",
    "name": "明日补T接回200股",
    "conditions_text": "价格 <= 8.86",
    "price": 8.83,                      // 触发瞬间的价格;取不到 → null
    "title": "价格提醒 · 001896.SZ",
    "body": "明日补T接回200股\n触发条件:价格 <= 8.86\n当前价:8.83"
  },
  "channels": [ { "channel": "console", "ok": true, "detail": "..." } ]
}
```

**约定**:
- **实时推送与断线补发共用同一个构造函数**(`build_fired_payload`)→ 字段完全一致,
  前端只写一套解析;靠 `trigger_id` 去重,同一次提醒不会弹两遍。
- **被冷却/日限流拦下的不广播** —— 那一次用户什么都没收到,再弹一次等于骗人。
- 心跳:每 30s 一个 `:heartbeat` 注释行。
- 字面量路径 `/stream` 必须注册在 `/{alert_id}` **之前**(FastAPI 按注册顺序匹配)。

#### 页面在后台时,各条通路的实际表现(2026-11-04 实测)

「浏览器开着但页面不在前台」= **能收到**,但**能不能看见**取决于哪条通路。
四层要分开看,别混成一句「收到了」:

| 层 | 后台标签页的表现 | 说明 |
|---|---|---|
| ① 事件送达 | ✅ SSE 连接**不断** | 实测后台 22s 连接数不变;EventSource 由浏览器进程维护,不随页面可见性断开 |
| ② 应用内弹窗 | ⚠️ DOM **渲染了**但**看不见** | 页面不在前台,弹窗在视口外 |
| ③ 应用内提示音 | ❌ 被浏览器**静音** | 后台标签页 AudioContext 挂起 |
| ④ **浏览器系统通知** | ✅ 弹到 Windows 通知中心,**且不自动消失** | `requireInteraction: true`;抓屏证实卡片常驻 |

**结论**:
- **唯一能在后台真正弹到眼前的通路是浏览器系统通知** → 必须先授权
  (`Notification.permission === 'granted'`),否则前三层之外什么都不会有。
  前端在「设置 → 通知 → 本机提醒 → 浏览器系统通知」提供授权入口。
- 标签页被 Chromium 丢弃(内存回收)时 SSE 会断,但**切回页面时靠首帧快照
  (最近 10 分钟)补发**,不丢。
- **多标签页同时开着**:每页各收一条 SSE → 每页弹一次应用内弹窗 + 一次系统通知
  (`tag` 相同会覆盖,不堆叠)。要「全局只弹一次」需在服务端去重。

> 判定「用户看得见」必须**抓屏看像素** —— API 返回「发送成功」不等于屏幕上有东西
> (见本节开头的 Win32 托盘气泡反例)。

#### GET /api/price-alerts/recent-fired

**降级轮询用**:SSE 连不上时前端退回来轮询它,别让用户漏掉提醒。
Query:`minutes`(默认 10,上限 120)、`limit`(默认 20,上限 100)。
响应 `{ "items": [PriceAlertFiredEvent], "count": n }` —— **只含 `status = "matched"`**
(被限流的 `skipped` 不算「响了」)。

#### POST /api/price-alerts/test-popup

**弹窗通路自检**(零副作用):广播一条**合成**的「提醒响了」事件,让用户当场验证
弹窗弹不弹得出来 —— 不然只能干等,分不清是「没到价」还是「弹窗坏了」。

Body(全可选,直接 POST `{}` 也能试):
```jsonc
{ "stock_code": "001896.SZ", "name": "测试标的",
  "conditions_text": "价格 <= 8.771", "price": 8.83 }
```
响应 `{ "ok": true, "stock_code": "...", "price": 8.83 }`。

⚠️ **不碰任何规则、不记流水、不消耗冷却/日限流额度**;走的是与真实触发
**完全相同**的广播路径(SSE → 前端弹窗)。

### 13.8.5 无效行情的过滤口径(v0.20 新增)

**背景**:2026-11-04 开盘 09:15 集合竞价瞬间,行情源对部分标的返回**占位值**
`price = 0.0, change_pct = -100.0`。这类值**不会让求值器报错** —— `0.0` 是合法数字,
求值器只会安静地给出错误答案。

**口径(全项目统一:行情取不到 = null / 不编数据)**

| 值 | 判定 | 处理 |
|---|---|---|
| `price <= 0` | 停牌 / 开盘瞬间占位值 | **该标的本轮不评估** |
| 非数字 | 数据源异常 | 同上 |
| `NaN` / `±inf` | 非有限值 | 同上(且**不是合法 JSON**,进响应会直接 500) |

**落点**

| 位置 | 处理 |
|---|---|
| `GET /api/price-alerts/stream` 的求值侧 | 调度器构造 `AlertContext` 前过滤 → 该标的本轮不评估,**不产生触发流水** |
| `GET /api/t-reminders/pending` | `current_price` 无效 → 返回 `null`(不显示 `0.000`,也不让 NaN 打挂序列化) |
| 预警**重新武装** | 无效行情 → **不武装**(判据「当前价不再满足预警条件」在无效值下会误判) |

**为什么不能靠数据源**:集合竞价、停牌、接口降级 —— 数据源返回占位值是**常态**。
防御必须做在消费侧。

**验收**:见 `docs/roadmap.md` 阶段 20(12 条回归测试 + 真实 dev DB 实测)。

---

## 13.9 做T操作历史(v0.16 新增 · v0.18 区分正反T)

### 13.9.1 GET /api/t-history/{stock_code}

**目的**:持仓详情弹窗右侧的「做T操作历史」—— 把这只票做过的每一次T记下来,
含 T 前/T 后成本价与两个盈亏口径。

**口径(单一,不搞多套推断)**

1. **做T分两个方向**,腿的先后顺序不同(v0.18):

   | `direction` | 中文 | 开腿 | 收腿 |
   |---|---|---|---|
   | `reverse` | 反T | 卖出(先卖) | 买回(后买) |
   | `forward` | 正T | 买入(先买) | 卖出(后卖) |

2. 同一标的的**全部流水**按链全序(`trade_date, trade_time or min, id`)走一遍,**双向 FIFO**:
   - 遇到**买入**:先闭合最早的**卖出开腿**(反T),剩余部分成为**买入开腿**(正T);
   - 遇到**卖出**:先闭合最早的**买入开腿**(正T),剩余部分成为**卖出开腿**(反T);
3. 配对**有时间窗口** —— 开腿与收腿相隔超过 `T_PAIR_WINDOW_DAYS`(默认 3 天)就不是做T,
   超窗口的开腿被冻结,不再参与后面的配对(见 §13.8 的「为什么要有时间窗口」);
4. 链尾没被闭合的开腿 = **挂单中**(`status = "pending"`):
   反T开腿未闭合 → 待接回;正T开腿未闭合 → 待卖出,都要列出来。
   挂单的开腿日期也必须落在窗口内(基准 = 链上最后一个流水的日期)。

   > v0.16 只有「先卖后买」一种,只有买入的流水会被**整段丢弃** ——
   > 用户手上明明还有正T(先买后卖)在等着,系统却看不见。v0.18 补上正T方向。

**两个盈亏口径(都要给)**

| 字段 | 公式 | 含义 | 挂单中时 |
|---|---|---|---|
| `t_pnl` | (卖出价 − 买入价) × T股数 | 做T差价盈亏 —— 两个方向都是「低买高卖赚差价」 | null(价差还不存在) |
| `realized_pnl` | (卖出价 − 卖出那一刻的摊薄成本) × 股数 | 卖出确认的已实现盈亏 | 反T有值(卖出即确认);正T为 null(还没卖) |

**成本价取自成本链**(基准 + 活链重放,见 `service.load_chain_context`)

- `cost_before` = **开腿那一刻**的持仓摊薄成本(反T = 卖出前;正T = 买入前);
- `cost_after` = **收腿之后**的持仓摊薄成本;
- 基准吸收掉的早期导入流水(`id <= base_tx_id`)没有逐笔成本快照 → 这两个字段为 **null**,
  不编数字(前端的「成本 前→后」列显示 `—`)。
- 成本口径 = 券商摊薄口径(v0.17),见 §13.10 —— 卖出按成交价回收净投入,
  所以 T 前后成本线**会变**(这不是 bug,与券商同行为)。

**响应 200**:
```jsonc
{
  "stock_code": "561980.SH",
  "stock_name": "半导体设备ETF招商",
  "items": [
    {
      "status": "closed",            // closed = 两腿都齐了;pending = 还挂着一腿
      "direction": "reverse",        // reverse = 反T(先卖后买) / forward = 正T(先买后卖)
      "sell_tx_id": 19,              // 反T:卖出腿是开腿;正T:卖出腿是收腿(未闭合时为 null)
      "sell_date": "2026-11-02",
      "sell_price": 0.462,
      "buy_tx_id": 29,               // 反T:买回腿是收腿;正T:买入腿是开腿(未闭合时为 null)
      "buy_date": "2026-11-03",
      "buy_price": 0.452,
      "shares": 200,
      "cost_before": 0.831,          // 开腿那一刻的摊薄成本价
      "cost_after": 0.827,           // 收腿之后的摊薄成本价
      "t_pnl": 2.0,                  // (0.462 − 0.452) × 200
      "realized_pnl": -73.8          // (0.462 − 0.831) × 200
    },
    {
      "status": "pending",
      "direction": "forward",        // 正T:买进了还没卖出去
      "sell_tx_id": null,
      "sell_date": null,
      "sell_price": null,
      "buy_tx_id": 30,
      "buy_date": "2026-11-03",
      "buy_price": 0.442,
      "shares": 200,
      "cost_before": 0.827,
      "cost_after": null,
      "t_pnl": null,                 // 还没卖 → 价差还不存在
      "realized_pnl": null           // 还没卖 → 已实现还没确认
    }
  ],
  "count": 2,
  "base_tx_id": 14                  // 基准吸收上界:<= 它的流水没有逐笔成本
}
```

**前端类型必须写驼峰**:`stockCode` / `stockName` / `status` / `direction` / `sellTxId` /
`sellDate` / `sellPrice` / `buyTxId` / `buyDate` / `buyPrice` / `shares` / `costBefore` /
`costAfter` / `tPnl` / `realizedPnl` / `baseTxId`。

**颜色口径**:涨红跌绿(`text-up` = 红 = 赚,`text-down` = 绿 = 亏)。

---

## 13.10 成本口径:券商摊薄口径(v0.17 口径变更)

### 13.10.1 问题

用户反馈「昨天录入流水后,成本和持仓对不上」。逐只比对券商持仓截图后定位到根因:
**系统内部记的是「加权平均剩余成本」,展示时又用 `(total_cost − realized_pnl) ÷ shares`
反推摊薄成本** —— 而基准里带的正是券商给的**累计已实现盈亏**,于是已实现被**二次扣减**。

实例(豫能控股 001896.SZ,券商 400 股 @18.940):

| 口径 | 算式 | 结果 |
|---|---|---|
| v0.10 展示(错) | (6231.20 + 50.60) ÷ 400 | 15.704 ✗ |
| v0.17 摊薄(对) | (9346.80 − 1772.00) ÷ 400 | 18.937 ✓ |

### 13.10.2 口径定义

券商持仓页的「成本价」= **摊薄成本** = 累计净投入 ÷ 当前持股数:

    摊薄成本 = (累计买入金额 − 累计卖出金额) ÷ 持股数

v0.17 起系统内部直接追踪**净投入**(摊薄总额),不再靠反推:

- 买入:净投入 += 成交价 × 股数
- 卖出:净投入 −= 成交价 × 股数(**按成交价回收**,不是按成本等比例冲减)
- 卖出确认的已实现 = (成交价 − 卖出前摊薄成本) × 股数
- 摊薄成本 = 净投入 ÷ 股数 → **卖出后会变**(低于成本卖 → 摊薄成本抬高),与券商同行为

### 13.10.3 影响面

| 位置 | 变化 |
|---|---|
| `positions.total_cost` / `transactions.total_cost_after` | 语义 = 摊薄总额(净投入),不再是加权剩余成本 |
| `GET /api/positions` 的 `avg_cost` | = 摊薄成本价(券商「成本价」) |
| `GET /api/positions` 的 `floating_pnl` | 按摊薄成本算 → 与券商持仓页同口径 |
| `POST /api/positions`(手动录入/截图导入) | `cost_price` = 券商摊薄成本价,录入值 = 展示值(不再受已实现影响) |
| `POST /api/positions/{code}/clear` 的预估已实现 | (清仓价 − 摊薄成本) × 股数,与链内口径一致 |
| 补T清单 `cost_before` / `cost_after` | 摊薄成本线(§13.8) |
| 做T历史 `cost_before` / `cost_after` / `realized_pnl` | 摊薄成本线(§13.9) |
| `POST /api/calculator` 试算 | 卖出后摊薄成本会变(`delta_cost` 不再恒为 0) |

### 13.10.4 基准(base_*)的语义

基准 = 「导入那一刻的真实持仓」,**摊薄口径**下:

- `base_shares` = 券商持仓股数
- `base_total_cost` = 券商**摊薄总额**(摊薄成本价 × 股数)
- `base_realized_pnl` = 券商给的**累计已实现盈亏**(**独立**存放,不从摊薄总额里扣)
- `base_tx_id` = 基准已吸收的流水 id 上界

推算公式(券商快照 → 基准):

    ΔS = 活链净股数,ΔD = 活链净现金流(买入加 / 卖出减)
    S0 = 券商股数 − ΔS
    D0 = 券商摊薄总额 − ΔD

一次性修正脚本:`backend/scripts/fix_base_to_broker.py`(带 `--dry-run`,幂等)。

### 13.10.5 验收

2026-11-03 实测(券商持仓截图 11 只):修正基准 + 全量重放后,**11 只摊薄成本与券商分毫不差**
(含华天科技股数 1000 → 1100、集成电路ETF嘉实基准 813.00 → 810.00 的修正)。

---

## 14. 错误码全局清单

| code | HTTP | 模块 | 用户文案 |
|---|---|---|---|
| INVALID_STOCK_CODE | 422 | 流水 | "代码格式错误,核对一下" |
| INSUFFICIENT_SHARES | 422 | 流水/计算器 | "这只票只剩 X 股了" |
| INVALID_PRICE | 422 | 流水/计算器 | "价格似乎有问题,核对一下" |
| STOCK_NOT_FOUND | 404 | 流水 | "找不到这只股票" |
| LLM_FAILED | 500 | 诊断 | "AI 评语暂时不可用" |
| QUOTE_SOURCE_UNAVAILABLE | 503 | 持仓 | "行情源不可用,显示陈旧数据" |(原 `AKSHARE_FAILED`:2026-10-29 ADR-0006 评估后不引入 akshare,错误码按实际实现改名)|
| INTERNAL_ERROR | 500 | 全局 | "服务异常,请重试" |
| INVALID_PROVIDER | 422 | LLM | "Provider 名称无效" |
| NO_KEY | 400 | LLM | "请先在设置页配置 Key" |
| INVALID_KEY | 401 | LLM | "Key 无效,请核对" |
| FORBIDDEN | 403 | LLM | "Key 权限不足" |
| LLM_TIMEOUT | 504 | LLM | "连接超时,网络可能不稳" |
| UNSUPPORTED_FORMAT | 415 | 截图 | "暂只支持 jpg/png/webp 格式" |
| FILE_TOO_LARGE | 413 | 截图 | "图片过大,请压缩后重试" |
| OCR_FAILED | 500 | 截图 | "OCR 失败,可粘贴外网模型输出" |
| INVALID_JSON | 422 | 截图降级 | "JSON 格式错误,请检查" |

---

## 15. 通用约定

### 14.1 时间
- 所有时间戳 ISO 8601 UTC:`2026-07-30T15:30:00`
- 日期:`YYYY-MM-DD`

### 14.2 金额
- **字符串传输**(精度保护)
- 前端用 `decimalFormat()` 工具格式化显示
- 后端 Python 用 `Decimal` 类型

### 14.3 错误响应格式
```json
{
  "code": "INVALID_STOCK_CODE",
  "message": "代码格式错误,核对一下",
  "detail": { "field": "stock_code", "value": "abc" }
}
```

### 14.4 字段命名
- 后端 Pydantic / 数据库:**snake_case**(`stock_code`)
- 前端 TS:**camelCase**(`stockCode`)
- 转换在 axios 拦截器自动完成(`frontend-arch §7.1`)