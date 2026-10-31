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
| note | str | 否 | ≤ 200 字 | 备注 |

**示例**:
```json
{
  "stock_code": "000001",
  "action": "buy",
  "shares": 500,
  "price": "10.500",
  "trade_date": "2026-07-30",
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
**目的**:修改一笔交易(只能改 note / shares / price,不能改 stock_code / action)

**请求体**(所有字段可选):
```json
{
  "shares": 500,
  "price": "10.500",
  "note": "改备注"
}
```

**响应 200**:同 POST

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
- `shares` / `avg_cost` 来自 transactions 聚合(加权平均)
- `stock_code` 统一为带市场后缀格式(`600519.SH` / `000001.SZ`,P3.5.1 起)
- `current_price` / `prev_close` 来自行情接口(新浪主 + 腾讯备),缓存 5 分钟
- `today_pnl` = `(current_price - prev_close) × shares`(今日盈亏)
- `floating_pnl` = `(current_price - avg_cost) × shares`(浮动盈亏)
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
    "板块热度": 20
  },
  "ai_comment": "买入价高于成本 8%,疑似追涨...",
  "ai_status": "success",
  "ai_provider": "deepseek",
  "ai_model": "deepseek-chat",
  "ai_latency_ms": 8200
}
```

**业务说明**:`ai_status` 取值:`pending` / `success` / `failed` / `no_key`(v2.1)

### 6.3 POST /api/diagnose/{trade_id}/regenerate

**目的**:用指定 Provider 重新生成评语(A/B 对比)

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| provider | str | 是 | deepseek / minimax / doubao |

**响应 202**:`{ "trade_id": 1, "status": "pending" }`

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
    "candidates_considered": 120, // 进入逐票算信号的候选数
    "total_picks": 12,
    "elapsed_sec": 8.2,
    "note": null
  },
  "groups": [
    {
      "kind": "dip_buy",
      "kind_label": "低吸信号",
      "count": 5,
      "picks": [
        {
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
        }
      ]
    }
  ],
  "all": [ /* 全部命中,按综合分降序 */ ],
  "kinds": [ { "kind": "main_force_move", "label": "主力异动" } ]
}
```

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
- 全市场扫描耗时较长(实测候选 120 只约 8s),前端超时设 300s。

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